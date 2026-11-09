"""Sales order lifecycle: create Draft, edit Draft, confirm (deduct stock), cancel (restore).

Status transitions (assignment Part 6):
    Draft     --edit-->    Draft       no stock change
    Draft     --confirm--> Confirmed   deduct ordered quantities
    Draft     --cancel-->  Cancelled   no stock change
    Confirmed --cancel-->  Cancelled   restore deducted quantities
    Cancelled              read-only

Values the browser sends that we IGNORE: rate, amount, totals, status, created_by,
order_date. They are always taken from the database or computed here.
"""
from datetime import date

from ..errors import Conflict, ValidationError
from ..extensions import db
from ..models import (
    MOVE_ORDER_CANCEL,
    MOVE_ORDER_CONFIRM,
    STATUS_CANCELLED,
    STATUS_CONFIRMED,
    STATUS_DRAFT,
    Customer,
    Product,
    SalesOrder,
    SalesOrderItem,
)
from ..permissions import get_order_for_user
from .money import MAX_STOCK, fits_money_column, line_amount, order_totals, parse_discount, parse_quantity
from .stock import lock_products, record_movement
from .transaction import unit_of_work


def _parse_id(value):
    if isinstance(value, bool):
        return None
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def parse_order_payload(payload):
    """Validate the shape of an order request.

    Expected: {"customer_id": 1, "discount_percentage": "10", "items": [{"product_id": 3, "quantity": 2}]}
    Returns (customer_id, discount, [(product_id, quantity), ...]). Collects every error.
    """
    if not isinstance(payload, dict):
        raise ValidationError("Request body must be a JSON object.")
    errors = []

    customer_id = _parse_id(payload.get("customer_id"))
    if customer_id is None:
        errors.append({"field": "customer_id", "message": "Select a customer."})

    discount = None
    try:
        discount = parse_discount(payload.get("discount_percentage"))
    except ValueError as exc:
        errors.append({"field": "discount_percentage", "message": str(exc)})

    raw_items = payload.get("items")
    lines = []
    if not isinstance(raw_items, list) or not raw_items:
        errors.append({"field": "items", "message": "Add at least one item."})
    else:
        seen = set()
        for index, raw in enumerate(raw_items):
            prefix = f"items[{index}]"
            if not isinstance(raw, dict):
                errors.append({"field": prefix, "message": "Each item must be an object."})
                continue
            product_id = _parse_id(raw.get("product_id"))
            if product_id is None:
                errors.append({"field": f"{prefix}.product_id", "message": f"Row {index + 1}: select a product."})
            elif product_id in seen:
                errors.append({"field": f"{prefix}.product_id",
                               "message": f"Row {index + 1}: this product is already in the order."})
            else:
                seen.add(product_id)
            try:
                quantity = parse_quantity(raw.get("quantity"))
            except ValueError as exc:
                errors.append({"field": f"{prefix}.quantity", "message": f"Row {index + 1}: {exc}"})
                quantity = None
            if product_id is not None and quantity is not None:
                lines.append((product_id, quantity))

    if errors:
        raise ValidationError("Please correct the order.", errors)
    return customer_id, discount, lines


def _active_customer(customer_id) -> Customer:
    customer = db.session.get(Customer, customer_id)
    if customer is None or not customer.is_active:
        raise ValidationError(
            "Please correct the order.",
            [{"field": "customer_id", "message": "Select an active customer."}],
        )
    return customer


def _active_products(product_ids):
    products = {
        p.id: p for p in db.session.execute(db.select(Product).where(Product.id.in_(product_ids))).scalars()
    }
    errors = []
    for index, product_id in enumerate(product_ids):
        product = products.get(product_id)
        if product is None:
            errors.append({"field": f"items[{index}].product_id", "message": f"Row {index + 1}: product not found."})
        elif not product.is_active:
            errors.append({"field": f"items[{index}].product_id",
                           "message": f"Row {index + 1}: {product.product_code} is inactive."})
    if errors:
        raise ValidationError("Please correct the order.", errors)
    return products


def _check_line_amounts(lines, rates):
    """Reject lines whose amount would not fit DECIMAL(12,2) (MySQL would refuse the row)."""
    errors = [
        {"field": f"items[{index}].quantity", "message": f"Row {index + 1}: the line amount is too large."}
        for index, (product_id, quantity) in enumerate(lines)
        if not fits_money_column(line_amount(quantity, rates[product_id]))
    ]
    if errors:
        raise ValidationError("Please correct the order.", errors)


def _recalculate(order):
    order.subtotal, order.discount_amount, order.grand_total = order_totals(
        [item.amount for item in order.items], order.discount_percentage
    )
    if not fits_money_column(order.subtotal):
        raise ValidationError("Please correct the order.",
                              [{"field": "items", "message": "The order total is too large."}])


def create_draft(user, payload) -> SalesOrder:
    customer_id, discount, lines = parse_order_payload(payload)
    with unit_of_work():
        _active_customer(customer_id)
        products = _active_products([product_id for product_id, _ in lines])
        _check_line_amounts(lines, {pid: p.price for pid, p in products.items()})
        order = SalesOrder(
            customer_id=customer_id,
            order_date=date.today(),
            status=STATUS_DRAFT,
            discount_percentage=discount,
            created_by=user.id,
        )
        # Insert lines in ascending product id order: each INSERT takes a shared lock on its
        # product row (foreign-key check), and every other path locks products in this order.
        for product_id, quantity in sorted(lines):
            rate = products[product_id].price  # current price, stored on the line
            order.items.append(
                SalesOrderItem(product_id=product_id, quantity=quantity, rate=rate, amount=line_amount(quantity, rate))
            )
        _recalculate(order)
        db.session.add(order)
        db.session.flush()  # assigns order.id (AUTO_INCREMENT) inside this transaction
        # Derived from the unique id, so two concurrent creates can never get the same number.
        order.order_number = f"SO-{order.order_date:%Y%m%d}-{order.id:05d}"
    return order


def update_draft(user, order_id, payload) -> SalesOrder:
    """Replace the editable parts of a Draft: customer, discount and the item list.

    Lines for products already on the order keep their stored rate; newly added products
    take the current price; products left out are removed.
    """
    customer_id, discount, lines = parse_order_payload(payload)
    with unit_of_work():
        order = get_order_for_user(order_id, user, lock=True)
        if order.status != STATUS_DRAFT:
            raise Conflict(f"Order {order.order_number} is {order.status} and can no longer be edited.",
                           code="ORDER_NOT_DRAFT")
        _active_customer(customer_id)
        products = _active_products([product_id for product_id, _ in lines])

        existing = {item.product_id: item for item in order.items}
        _check_line_amounts(lines, {pid: existing[pid].rate if pid in existing else p.price
                                    for pid, p in products.items()})
        wanted = dict(lines)
        for item in list(order.items):
            if item.product_id not in wanted:
                order.items.remove(item)  # delete-orphan removes the row
        for product_id, quantity in sorted(lines):  # ascending id: see create_draft
            item = existing.get(product_id)
            if item is None:
                rate = products[product_id].price
                order.items.append(SalesOrderItem(product_id=product_id, quantity=quantity, rate=rate,
                                                  amount=line_amount(quantity, rate)))
            else:
                item.quantity = quantity
                item.amount = line_amount(quantity, item.rate)
        order.customer_id = customer_id
        order.discount_percentage = discount
        _recalculate(order)
    return order


def _require_active_customer_locked(customer_id):
    """Read the customer with a shared lock so a concurrent deactivation can't slip past."""
    customer = db.session.execute(
        db.select(Customer).where(Customer.id == customer_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    ).scalar_one()
    if not customer.is_active:
        raise Conflict(f"Customer '{customer.name}' is inactive. Reactivate the customer or cancel the order.",
                       code="CUSTOMER_INACTIVE")


def confirm_order(user, order_id, _after_lock=None) -> SalesOrder:
    """Confirm a Draft and deduct stock, all in ONE transaction.

    Concurrency approach (pessimistic locking):
      1. Lock the order row (and its items). A second confirm of the same order waits
         here, then sees status 'Confirmed' and is rejected: no double deduction.
      2. Lock every product on the order, in ascending id order. Two orders competing for
         the same product are serialised: the second waits until the first commits and
         then sees the reduced stock, so stock can never go negative.
      3. Check ALL lines; if any is short, raise and roll back (nothing changes).
      4. Deduct stock, write ORDER_CONFIRM movements, set status, commit (locks released).

    `_after_lock` is a test hook called while the locks are held.
    """
    with unit_of_work():
        order = get_order_for_user(order_id, user, lock=True)
        if order.status != STATUS_DRAFT:
            raise Conflict(f"Order {order.order_number} is already {order.status}; it cannot be confirmed.",
                           code="ORDER_NOT_DRAFT")
        _require_active_customer_locked(order.customer_id)
        products = lock_products([item.product_id for item in order.items])
        if _after_lock is not None:
            _after_lock()

        problems = []
        for item in order.items:
            product = products[item.product_id]
            if not product.is_active:
                problems.append({"product_code": product.product_code, "message": "Product is inactive."})
            elif product.stock_quantity < item.quantity:
                problems.append({
                    "product_code": product.product_code,
                    "requested": item.quantity,
                    "available": product.stock_quantity,
                    "message": f"Only {product.stock_quantity} in stock, {item.quantity} requested.",
                })
        if problems:
            only_stock = all("requested" in problem for problem in problems)
            raise Conflict(
                "Order cannot be confirmed: insufficient stock." if only_stock
                else "Order cannot be confirmed: some products are inactive or short of stock.",
                details=problems,
                code="INSUFFICIENT_STOCK" if only_stock else "CANNOT_CONFIRM",
            )

        for item in order.items:
            product = products[item.product_id]
            product.stock_quantity -= item.quantity
            record_movement(product, MOVE_ORDER_CONFIRM, -item.quantity,
                            f"Order {order.order_number} confirmed", user, order)
        order.status = STATUS_CONFIRMED
    return order


def cancel_order(user, order_id) -> SalesOrder:
    """Cancel a Draft (no stock change) or a Confirmed order (restore stock once)."""
    with unit_of_work():
        order = get_order_for_user(order_id, user, lock=True)
        if order.status == STATUS_CANCELLED:
            raise Conflict(f"Order {order.order_number} is already Cancelled.", code="ORDER_ALREADY_CANCELLED")
        if order.status == STATUS_CONFIRMED:
            products = lock_products([item.product_id for item in order.items])
            for item in order.items:
                product = products[item.product_id]
                if product.stock_quantity + item.quantity > MAX_STOCK:
                    raise Conflict(f"Cannot restore stock for {product.product_code}: the stock limit would be exceeded.",
                                   code="STOCK_LIMIT")
                product.stock_quantity += item.quantity
                record_movement(product, MOVE_ORDER_CANCEL, item.quantity,
                                f"Order {order.order_number} cancelled", user, order)
        order.status = STATUS_CANCELLED
    return order


def list_orders_query(user, status=None, q=None):
    """Admins see every order; Sales Users only their own (filtered in SQL, not in the UI)."""
    query = db.select(SalesOrder).join(SalesOrder.customer).order_by(SalesOrder.id.desc())
    if not user.is_admin:
        query = query.where(SalesOrder.created_by == user.id)
    if status in (STATUS_DRAFT, STATUS_CONFIRMED, STATUS_CANCELLED):
        query = query.where(SalesOrder.status == status)
    if q:
        like = f"%{q.strip()}%"
        query = query.where(db.or_(SalesOrder.order_number.like(like), Customer.name.like(like)))
    return query
