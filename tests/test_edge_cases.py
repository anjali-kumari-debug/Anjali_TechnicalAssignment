"""Regression tests for edge cases found in code review."""
import io

from app.extensions import db
from app.models import Customer, Product, User


def test_huge_quantity_is_a_validation_error_not_a_500(make, client_for):
    user, customer = make.user(), make.customer()
    product = make.product(price="1500.00")
    response = client_for(user).post("/api/orders", json={
        "customer_id": customer, "items": [{"product_id": product, "quantity": 10_000_000}]})
    assert response.status_code == 400
    assert response.get_json()["error"]["details"][0]["field"] == "items[0].quantity"


def test_order_total_too_large_is_rejected(make, client_for):
    user, customer = make.user(), make.customer()
    a, b = make.product(price="6000000000.00"), make.product(price="6000000000.00")
    response = client_for(user).post("/api/orders", json={
        "customer_id": customer, "items": [{"product_id": a, "quantity": 1}, {"product_id": b, "quantity": 1}]})
    assert response.status_code == 400
    assert "too large" in response.get_data(as_text=True)


def test_stock_cannot_exceed_int_limit(make, client_for):
    product = make.product(stock=0)
    admin = client_for(make.admin())
    for _ in range(3):
        admin.post(f"/products/{product}/adjust", data={"quantity_change": "999999999", "reason": "Big delivery"})
    assert make.stock(product) == 1_999_999_998  # third adjustment refused


def test_delete_refused_by_foreign_key_is_409_not_500(make, client_for, monkeypatch):
    """Simulates an order created between the reference check and the DELETE."""
    from app.services import catalog
    customer = make.customer(name="Racy Customer")
    make.order(make.user(), customer, [(make.product(), 1)])
    monkeypatch.setattr(catalog, "customer_has_orders", lambda customer_id: False)
    page = client_for(make.admin()).post(f"/customers/{customer}/delete", follow_redirects=True)
    assert page.status_code == 200 and "cannot be deleted" in page.get_data(as_text=True)
    assert make.run(lambda: db.session.get(Customer, customer) is not None)


def test_login_next_with_backslash_stays_on_site(make, client_for):
    from werkzeug.security import generate_password_hash
    make.run(lambda: (db.session.add(User(name="B", email="b@test.example", role="Admin",
                      password_hash=generate_password_hash("pw-12345678", method="pbkdf2:sha256:1000"))),
                      db.session.commit()))
    for target in ["/\\evil.example/x", "//evil.example", "https://evil.example", "/%09/evil.example", "/%5Cevil.example"]:
        client = client_for(None)
        response = client.post(f"/login?next={target}", data={"email": "b@test.example", "password": "pw-12345678"})
        assert response.headers["Location"] == "/", target


def test_anonymous_api_post_with_csrf_enabled_gets_401(app, client_for, monkeypatch):
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", True)
    response = client_for(None).post("/api/orders", json={})
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "UNAUTHORIZED"


def test_csv_invalid_code_does_not_crash(make, client_for):
    make.product(code="PRD-001")
    csv_text = ("product_code,product_name,category,price,stock_quantity,status\n"
                "prd 001,Spacey,Cat,10,1,Active\nPRD-00É,Accent,Cat,10,1,Active\n")
    response = client_for(make.admin()).post(
        "/products/import", data={"file": (io.BytesIO(csv_text.encode()), "x.csv")}, content_type="multipart/form-data")
    assert response.status_code == 400
    assert "is not a valid code" in response.get_data(as_text=True)
    assert make.count(Product) == 1


def test_report_rejects_extreme_dates(make, client_for):
    page = client_for(make.admin()).get("/reports/customer-sales?date_from=2026-01-01&date_to=9999-12-31")
    assert page.status_code == 200 and "Year must be between" in page.get_data(as_text=True)


def test_names_with_quotes_are_not_injected_into_javascript(make, client_for):
    make.customer(name="O'Brien \"Traders\" <b>")
    page = client_for(make.admin()).get("/customers").get_data(as_text=True)
    assert "onsubmit" not in page
    assert 'data-confirm="Delete customer O&#39;Brien &#34;Traders&#34; &lt;b&gt;? This cannot be undone."' in page


def test_draft_lines_are_stored_in_product_id_order(make, call_as):
    from app.services import orders
    user, customer = make.user(), make.customer()
    first, second = make.product(), make.product()
    order = call_as(user, orders.create_draft, {"customer_id": customer, "items": [
        {"product_id": second, "quantity": 1}, {"product_id": first, "quantity": 2}]})
    assert [item["product_id"] for item in order["items"]] == [first, second]


def test_confirm_refused_if_customer_deactivated_after_draft(make, client_for):
    user, customer, product = make.user(), make.customer(), make.product(stock=5)
    order_id = make.order(user, customer, [(product, 1)])
    make.run(lambda: (setattr(db.session.get(Customer, customer), "is_active", False), db.session.commit()))
    response = client_for(user).post(f"/api/orders/{order_id}/confirm")
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "CUSTOMER_INACTIVE"
    assert make.stock(product) == 5 and make.status(order_id) == "Draft"


def test_client_supplied_order_date_is_ignored(make, client_for):
    from datetime import date
    user, customer, product = make.user(), make.customer(), make.product()
    body = client_for(user).post("/api/orders", json={
        "customer_id": customer, "order_date": "2001-01-01", "items": [{"product_id": product, "quantity": 1}]}).get_json()
    assert body["order_date"] == date.today().isoformat()


def test_lock_timeout_is_reported_as_409_busy(make, client_for, monkeypatch):
    from sqlalchemy.exc import OperationalError
    from app.services import orders

    def locked(*args, **kwargs):
        raise OperationalError("SELECT ... FOR UPDATE", {}, Exception(1205, "Lock wait timeout exceeded"))

    monkeypatch.setattr(orders, "confirm_order", locked)
    response = client_for(make.user()).post("/api/orders/1/confirm")
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "BUSY"


def test_session_cookie_flags(app):
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"


def test_seed_command_creates_sample_data(app, make, monkeypatch):
    from app.models import SalesOrder
    monkeypatch.setenv("SEED_ADMIN_PASSWORD", "Admin@12345")
    monkeypatch.setenv("SEED_SALES_PASSWORD", "Sales@12345")
    result = app.test_cli_runner().invoke(args=["seed"])
    assert result.exit_code == 0, result.output
    assert make.count(User) == 3 and make.count(Product) == 6
    example = make.run(lambda: db.session.execute(
        db.select(SalesOrder.grand_total).order_by(SalesOrder.id).limit(1)).scalar())
    assert str(example) == "4050.00"
    # Ledger invariant holds for the seeded data too
    from app.models import StockMovement
    mismatches = make.run(lambda: [p.product_code for p in db.session.execute(db.select(Product)).scalars()
                                   if p.stock_quantity != (db.session.execute(
                                       db.select(db.func.coalesce(db.func.sum(StockMovement.quantity_change), 0))
                                       .where(StockMovement.product_id == p.id)).scalar())])
    assert mismatches == []
