"""Reports (Admin only). Written as plain SQL so the queries can be read and explained
as-is; the same SQL appears in sql/queries.sql. Sales reports use Confirmed orders only."""
from datetime import date, timedelta

from sqlalchemy import text

from ..errors import ValidationError
from ..extensions import db
from .money import parse_quantity

CUSTOMER_SALES_SUMMARY = text("""
    SELECT c.id,
           c.name,
           c.city,
           c.is_active,
           COUNT(so.id)                     AS confirmed_orders,
           COALESCE(SUM(so.grand_total), 0) AS total_sales
    FROM customers c
    LEFT JOIN sales_orders so
           ON so.customer_id = c.id
          AND so.status = 'Confirmed'
          AND so.order_date >= :date_from
          AND so.order_date <  :date_to_exclusive
    GROUP BY c.id, c.name, c.city, c.is_active
    ORDER BY total_sales DESC, c.name
""")
# Why it is written this way:
#  * LEFT JOIN keeps customers with no Confirmed orders (they show 0 / 0.00).
#  * The status and date filters are in the ON clause. In WHERE they would discard the
#    NULL rows produced for those customers and turn the LEFT JOIN into an INNER JOIN.
#  * sales_order_items is NOT joined: grand_total already lives on the order, and joining
#    items would repeat each order once per item and inflate COUNT and SUM.
#  * COUNT(so.id), not COUNT(*): COUNT(*) would count 1 for a customer with no orders.

PRODUCT_SALES_SUMMARY = text("""
    SELECT p.id,
           p.product_code,
           p.name,
           SUM(soi.quantity) AS quantity_sold,
           SUM(soi.amount)   AS gross_value
    FROM sales_order_items soi
    JOIN sales_orders so ON so.id = soi.sales_order_id AND so.status = 'Confirmed'
    JOIN products p      ON p.id = soi.product_id
    GROUP BY p.id, p.product_code, p.name
    ORDER BY quantity_sold DESC, p.product_code
""")
# gross_value is the sum of line amounts (qty x rate) BEFORE the order-level discount.

LOW_STOCK = text("""
    SELECT id, product_code, name, category, stock_quantity, is_active
    FROM products
    WHERE stock_quantity < :threshold
    ORDER BY stock_quantity, product_code
""")

STOCK_MOVEMENT_HISTORY = text("""
    SELECT sm.id,
           sm.created_at,
           p.product_code,
           p.name          AS product_name,
           sm.movement_type,
           sm.quantity_change,
           so.order_number,
           sm.reason,
           u.name          AS created_by
    FROM stock_movements sm
    JOIN products p          ON p.id = sm.product_id
    JOIN users u             ON u.id = sm.created_by
    LEFT JOIN sales_orders so ON so.id = sm.related_order_id
    WHERE (:product_id IS NULL OR sm.product_id = :product_id)
    ORDER BY sm.created_at DESC, sm.id DESC
    LIMIT 500
""")


def _parse_date(value, field):
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValidationError("Invalid date range.", [{"field": field, "message": "Use the format YYYY-MM-DD."}]) from None
    if not 1900 <= parsed.year <= 9998:
        raise ValidationError("Invalid date range.", [{"field": field, "message": "Year must be between 1900 and 9998."}])
    return parsed


def customer_sales_summary(date_from_raw=None, date_to_raw=None):
    """Both dates are inclusive. Defaults: first day of the current month to today."""
    today = date.today()
    date_from = _parse_date(date_from_raw, "date_from") if date_from_raw else today.replace(day=1)
    date_to = _parse_date(date_to_raw, "date_to") if date_to_raw else today
    if date_from > date_to:
        raise ValidationError("Invalid date range.", [{"field": "date_from", "message": "'From' must be on or before 'To'."}])
    rows = db.session.execute(
        CUSTOMER_SALES_SUMMARY, {"date_from": date_from, "date_to_exclusive": date_to + timedelta(days=1)}
    ).mappings().all()
    return rows, date_from, date_to


def product_sales_summary():
    return db.session.execute(PRODUCT_SALES_SUMMARY).mappings().all()


def low_stock(threshold_raw):
    try:
        threshold = parse_quantity(threshold_raw, field="Threshold", allow_zero=True)
    except ValueError as exc:
        raise ValidationError("Invalid threshold.", [{"field": "threshold", "message": str(exc)}]) from None
    return db.session.execute(LOW_STOCK, {"threshold": threshold}).mappings().all(), threshold


def stock_movement_history(product_id=None):
    return db.session.execute(STOCK_MOVEMENT_HISTORY, {"product_id": product_id}).mappings().all()
