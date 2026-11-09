"""Report semantics (Part 9). Reports use Confirmed orders only."""
from datetime import date, timedelta

from app.extensions import db
from app.models import SalesOrder
from app.services import reports


def _confirm(client, order_id):
    assert client.post(f"/api/orders/{order_id}/confirm").status_code == 200


def _set_date(make, order_id, day):
    make.run(lambda: (setattr(db.session.get(SalesOrder, order_id), "order_date", day), db.session.commit()))


def test_customer_summary_counts_multi_item_order_once_and_keeps_zero_customers(make, client_for):
    admin_id = make.admin()
    admin = client_for(admin_id)
    buyer = make.customer(name="Buyer")
    idle = make.customer(name="Idle")
    p1, p2, p3 = make.product(price="100.00"), make.product(price="50.00"), make.product(price="10.00")
    multi = make.order(admin_id, buyer, [(p1, 2), (p2, 2), (p3, 5)], discount="10")  # 350 - 35 = 315
    _confirm(admin, multi)
    draft = make.order(admin_id, idle, [(p1, 1)])          # Draft: must not count
    cancelled = make.order(admin_id, idle, [(p1, 1)])
    _confirm(admin, cancelled)
    admin.post(f"/api/orders/{cancelled}/cancel")           # Cancelled: must not count

    rows = make.run(lambda: {r["name"]: (r["confirmed_orders"], str(r["total_sales"]))
                             for r in reports.customer_sales_summary()[0]})
    assert rows["Buyer"] == (1, "315.00")
    assert rows["Idle"] == (0, "0.00")
    assert draft


def test_customer_summary_date_range_is_inclusive(make, client_for):
    admin_id = make.admin()
    admin = client_for(admin_id)
    customer = make.customer(name="Dated")
    product = make.product(price="100.00")
    inside = make.order(admin_id, customer, [(product, 1)])
    outside = make.order(admin_id, customer, [(product, 2)])
    _confirm(admin, inside)
    _confirm(admin, outside)
    _set_date(make, inside, date(2026, 3, 31))
    _set_date(make, outside, date(2026, 4, 1))

    rows, *_ = make.run(lambda: reports.customer_sales_summary("2026-03-01", "2026-03-31"))
    totals = {r["name"]: str(r["total_sales"]) for r in rows}
    assert totals["Dated"] == "100.00"


def test_customer_summary_rejects_bad_ranges(make, client_for):
    admin = client_for(make.admin())
    page = admin.get("/reports/customer-sales?date_from=2026-05-01&date_to=2026-04-01").get_data(as_text=True)
    assert "on or before" in page
    page = admin.get("/reports/customer-sales?date_from=yesterday").get_data(as_text=True)
    assert "YYYY-MM-DD" in page


def test_product_summary_is_gross_value_before_discount(make, client_for):
    admin_id = make.admin()
    admin = client_for(admin_id)
    customer = make.customer()
    product = make.product(price="200.00", code="GROSS-1")
    _confirm(admin, make.order(admin_id, customer, [(product, 3)], discount="20"))
    make.order(admin_id, customer, [(product, 7)])  # Draft, ignored
    rows = make.run(lambda: [dict(r) for r in reports.product_sales_summary()])
    assert len(rows) == 1
    assert rows[0]["quantity_sold"] == 3 and str(rows[0]["gross_value"]) == "600.00"


def test_low_stock_is_strictly_below_threshold(make, client_for):
    make.product(stock=4, code="LOW-4")
    make.product(stock=5, code="LOW-5")
    rows, _ = make.run(lambda: reports.low_stock("5"))
    assert [r["product_code"] for r in rows] == ["LOW-4"]
    page = client_for(make.admin()).get("/reports/low-stock?threshold=-3").get_data(as_text=True)
    assert "cannot be negative" in page


def test_stock_movement_history_shows_order_numbers(make, client_for):
    admin_id = make.admin()
    admin = client_for(admin_id)
    product = make.product(stock=10)
    order_id = make.order(admin_id, make.customer(), [(product, 2)])
    _confirm(admin, order_id)
    rows = make.run(lambda: [dict(r) for r in reports.stock_movement_history(product)])
    assert [r["movement_type"] for r in rows] == ["ORDER_CONFIRM", "OPENING_STOCK"]
    assert rows[0]["order_number"].startswith("SO-") and rows[0]["quantity_change"] == -2
    assert admin.get(f"/reports/stock-movements?product_id={product}").status_code == 200


def test_reports_pages_render(make, client_for):
    admin = client_for(make.admin())
    today = date.today()
    for url in ["/reports/customer-sales", f"/reports/customer-sales?date_from={today - timedelta(days=30)}",
                "/reports/product-sales", "/reports/low-stock?threshold=10", "/reports/stock-movements"]:
        assert admin.get(url).status_code == 200, url
