"""Customer and product master data: validation, search, create/edit, safe delete."""
import re

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from ..errors import Conflict, NotFound, ValidationError
from ..extensions import db
from ..models import MOVE_OPENING, Customer, Product, SalesOrder, SalesOrderItem, StockMovement
from .money import parse_money, parse_quantity
from .stock import record_movement
from .transaction import unit_of_work

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MOBILE_RE = re.compile(r"^\+?[0-9][0-9 \-]{6,18}[0-9]$")
PRODUCT_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9_\-]{0,49}$")


def normalize_code(code) -> str:
    """Product codes are compared case-insensitively by MySQL (utf8mb4_0900_ai_ci), so we
    store them trimmed and upper-cased to make 'prd-001' and 'PRD-001' the same code."""
    return (code or "").strip().upper()


def parse_bool(value, default=True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on", "active")


def _required_text(data, field, label, max_len, errors):
    value = (data.get(field) or "").strip()
    if not value:
        errors.append({"field": field, "message": f"{label} is required."})
    elif len(value) > max_len:
        errors.append({"field": field, "message": f"{label} must be {max_len} characters or fewer."})
    return value


# ---------------------------------------------------------------- customers

def validate_customer(data):
    errors = []
    clean = {
        "name": _required_text(data, "name", "Name", 150, errors),
        "email": _required_text(data, "email", "Email", 150, errors).lower(),
        "mobile": _required_text(data, "mobile", "Mobile", 20, errors),
        "city": _required_text(data, "city", "City", 100, errors),
        "is_active": parse_bool(data.get("is_active"), default=True),
    }
    if clean["email"] and not EMAIL_RE.match(clean["email"]):
        errors.append({"field": "email", "message": "Enter a valid email address."})
    if clean["mobile"] and not MOBILE_RE.match(clean["mobile"]):
        errors.append({"field": "mobile", "message": "Enter a valid mobile number (digits, optional +, spaces or -)."})
    if errors:
        raise ValidationError("Please correct the highlighted fields.", errors)
    return clean


def get_customer(customer_id) -> Customer:
    customer = db.session.get(Customer, customer_id)
    if customer is None:
        raise NotFound(f"Customer {customer_id} was not found.")
    return customer


def search_customers(q=None, status=None, active_only=False):
    """Search by name, email or mobile; filter by 'active' / 'inactive'."""
    query = db.select(Customer).order_by(Customer.name)
    if q:
        like = f"%{q.strip()}%"
        query = query.where(or_(Customer.name.like(like), Customer.email.like(like), Customer.mobile.like(like)))
    if active_only or status == "active":
        query = query.where(Customer.is_active.is_(True))
    elif status == "inactive":
        query = query.where(Customer.is_active.is_(False))
    return query


def create_customer(data) -> Customer:
    clean = validate_customer(data)
    with unit_of_work():
        customer = Customer(**clean)
        db.session.add(customer)
    return customer


def update_customer(customer_id, data) -> Customer:
    clean = validate_customer(data)
    with unit_of_work():
        customer = get_customer(customer_id)
        for key, value in clean.items():
            setattr(customer, key, value)
    return customer


def customer_has_orders(customer_id) -> bool:
    return db.session.execute(
        db.select(SalesOrder.id).where(SalesOrder.customer_id == customer_id).limit(1)
    ).first() is not None


def delete_customer(customer_id):
    """Delete only if no order (of any status) references the customer."""
    def in_use(name):
        return Conflict(f"Customer '{name}' has orders and cannot be deleted. Deactivate the customer instead.",
                        code="CUSTOMER_IN_USE")
    customer = get_customer(customer_id)
    name = customer.name
    try:
        with unit_of_work():
            if customer_has_orders(customer_id):
                raise in_use(name)
            db.session.delete(customer)
    except IntegrityError:
        # An order was created for this customer between our check and the DELETE;
        # the foreign key (ON DELETE RESTRICT) refused the delete.
        raise in_use(name) from None


# ---------------------------------------------------------------- products

def validate_product(data, creating):
    errors = []
    code = normalize_code(data.get("product_code"))
    if not code:
        errors.append({"field": "product_code", "message": "Product code is required."})
    elif not PRODUCT_CODE_RE.match(code):
        errors.append({"field": "product_code",
                       "message": "Product code may contain letters, digits, '-' and '_' (max 50)."})
    clean = {
        "product_code": code,
        "name": _required_text(data, "name", "Name", 150, errors),
        "category": _required_text(data, "category", "Category", 100, errors),
        "is_active": parse_bool(data.get("is_active"), default=True),
    }
    try:
        clean["price"] = parse_money(data.get("price"), field="Price")
    except ValueError as exc:
        errors.append({"field": "price", "message": str(exc)})
    if creating:
        raw_stock = data.get("stock_quantity")
        if raw_stock is None or (isinstance(raw_stock, str) and not raw_stock.strip()):
            raw_stock = 0
        try:
            clean["stock_quantity"] = parse_quantity(raw_stock, field="Opening stock", allow_zero=True)
        except ValueError as exc:
            errors.append({"field": "stock_quantity", "message": str(exc)})
    if errors:
        raise ValidationError("Please correct the highlighted fields.", errors)
    return clean


def get_product(product_id) -> Product:
    product = db.session.get(Product, product_id)
    if product is None:
        raise NotFound(f"Product {product_id} was not found.")
    return product


def search_products(q=None, category=None, status=None, active_only=False):
    """Search by product code or name; filter by category and 'active' / 'inactive'."""
    query = db.select(Product).order_by(Product.product_code)
    if q:
        like = f"%{q.strip()}%"
        query = query.where(or_(Product.product_code.like(like), Product.name.like(like)))
    if category:
        query = query.where(Product.category == category)
    if active_only or status == "active":
        query = query.where(Product.is_active.is_(True))
    elif status == "inactive":
        query = query.where(Product.is_active.is_(False))
    return query


def product_categories(active_only=False):
    query = db.select(Product.category).distinct().order_by(Product.category)
    if active_only:
        query = query.where(Product.is_active.is_(True))
    return db.session.execute(query).scalars().all()


def _code_taken(code, exclude_id=None) -> bool:
    query = db.select(Product.id).where(Product.product_code == code)
    if exclude_id is not None:
        query = query.where(Product.id != exclude_id)
    return db.session.execute(query.limit(1)).first() is not None


def _duplicate_code_error(code):
    return ValidationError(
        "Please correct the highlighted fields.",
        [{"field": "product_code", "message": f"Product code {code} already exists."}],
    )


def create_product(data, user) -> Product:
    """Create a product. Opening stock > 0 is recorded as an OPENING_STOCK movement."""
    clean = validate_product(data, creating=True)
    if _code_taken(clean["product_code"]):
        raise _duplicate_code_error(clean["product_code"])
    try:
        with unit_of_work():
            product = Product(**clean)
            db.session.add(product)
            db.session.flush()  # get product.id for the movement row
            if product.stock_quantity > 0:
                record_movement(product, MOVE_OPENING, product.stock_quantity, "Opening stock", user)
    except IntegrityError:
        # Another request inserted the same code between our check and our insert.
        raise _duplicate_code_error(clean["product_code"]) from None
    return product


def update_product(product_id, data) -> Product:
    """Edit product details. Stock is NOT editable here: use a stock adjustment so the
    change is recorded as a movement with a reason."""
    clean = validate_product(data, creating=False)
    if _code_taken(clean["product_code"], exclude_id=product_id):
        raise _duplicate_code_error(clean["product_code"])
    try:
        with unit_of_work():
            product = get_product(product_id)
            for key, value in clean.items():
                setattr(product, key, value)
    except IntegrityError:
        raise _duplicate_code_error(clean["product_code"]) from None
    return product


def product_is_referenced(product_id) -> bool:
    in_orders = db.session.execute(
        db.select(SalesOrderItem.id).where(SalesOrderItem.product_id == product_id).limit(1)
    ).first()
    in_movements = db.session.execute(
        db.select(StockMovement.id).where(StockMovement.product_id == product_id).limit(1)
    ).first()
    return in_orders is not None or in_movements is not None


def delete_product(product_id):
    """Delete only if no order item and no stock movement references the product."""
    product = get_product(product_id)
    in_use = Conflict(
        f"Product {product.product_code} is used in orders or stock history and cannot be deleted. "
        "Deactivate it instead.",
        code="PRODUCT_IN_USE",
    )
    try:
        with unit_of_work():
            if product_is_referenced(product_id):
                raise in_use
            db.session.delete(product)
    except IntegrityError:
        # Referenced concurrently, after our check: the foreign key refused the delete.
        raise in_use from None
