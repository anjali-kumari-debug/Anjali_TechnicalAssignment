"""Stock changes. Every change to products.stock_quantity goes through here and writes a
stock_movements row, so stock_quantity always equals the sum of its movements."""
import re

from ..errors import Conflict, NotFound, ValidationError
from ..extensions import db
from ..models import MOVE_ADJUSTMENT, Product, StockMovement
from .money import MAX_STOCK
from .transaction import unit_of_work


def record_movement(product, movement_type, quantity_change, reason, user, order=None):
    """Add a movement row to the current transaction (no commit)."""
    db.session.add(
        StockMovement(
            product_id=product.id,
            movement_type=movement_type,
            quantity_change=quantity_change,
            related_order_id=order.id if order is not None else None,
            reason=reason,
            created_by=user.id,
        )
    )


def lock_products(product_ids):
    """SELECT ... FOR UPDATE the given products, always in ascending id order.

    Every code path that changes stock locks products in this same order, so two
    transactions can never each hold a lock the other one is waiting for (deadlock).
    Returns {product_id: Product}.
    """
    ids = sorted(set(product_ids))
    if not ids:
        return {}
    rows = db.session.execute(
        db.select(Product)
        .where(Product.id.in_(ids))
        .order_by(Product.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalars()
    return {product.id: product for product in rows}


def parse_adjustment(delta_raw, reason_raw):
    errors = []
    delta = None
    text = "" if delta_raw is None or isinstance(delta_raw, bool) else str(delta_raw).strip()
    if re.fullmatch(r"[+-]?[0-9]{1,9}", text) and int(text) != 0:
        delta = int(text)
    else:
        errors.append({"field": "quantity_change", "message": "Enter a non-zero whole number, e.g. 10 or -5."})
    reason = (reason_raw or "").strip()
    if not reason:
        errors.append({"field": "reason", "message": "A reason is required for every stock adjustment."})
    elif len(reason) > 255:
        errors.append({"field": "reason", "message": "Reason must be 255 characters or fewer."})
    if errors:
        raise ValidationError("Please correct the stock adjustment.", errors)
    return delta, reason


def adjust_stock(user, product_id, delta_raw, reason_raw):
    """Admin increases (+) or decreases (-) stock with a mandatory reason."""
    delta, reason = parse_adjustment(delta_raw, reason_raw)
    with unit_of_work():
        product = lock_products([product_id]).get(product_id)
        if product is None:
            raise NotFound(f"Product {product_id} was not found.")
        new_stock = product.stock_quantity + delta
        if new_stock < 0:
            raise Conflict(
                f"Cannot remove {-delta} units of {product.product_code}: only {product.stock_quantity} in stock.",
                code="INSUFFICIENT_STOCK",
            )
        if new_stock > MAX_STOCK:
            raise Conflict(f"Stock for {product.product_code} cannot exceed {MAX_STOCK:,} units.", code="STOCK_LIMIT")
        product.stock_quantity = new_stock
        record_movement(product, MOVE_ADJUSTMENT, delta, reason, user)
    return product
