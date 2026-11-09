"""Customer/product management, safe delete and stock adjustments (Parts 3, 4, 6)."""
from app.extensions import db
from app.models import Customer, Product, StockMovement


def _exists(make, model, row_id):
    return make.run(lambda: db.session.get(model, row_id) is not None)


def test_customer_referenced_by_any_order_cannot_be_deleted(make, client_for):
    admin = make.admin()
    customer = make.customer()
    product = make.product()
    order_id = make.order(make.user(), customer, [(product, 1)])
    client = client_for(admin)
    client.post(f"/api/orders/{order_id}/cancel")  # even a Cancelled order counts
    response = client.post(f"/customers/{customer}/delete", follow_redirects=True)
    assert "cannot be deleted" in response.get_data(as_text=True)
    assert _exists(make, Customer, customer)


def test_unreferenced_customer_can_be_deleted(make, client_for):
    customer = make.customer()
    client_for(make.admin()).post(f"/customers/{customer}/delete")
    assert not _exists(make, Customer, customer)


def test_product_with_orders_or_movements_cannot_be_deleted(make, client_for):
    admin = client_for(make.admin())
    with_stock = make.product(stock=5)           # has an OPENING_STOCK movement
    in_order = make.product(stock=0)
    make.order(make.user(), make.customer(), [(in_order, 1)])
    for product in (with_stock, in_order):
        page = admin.post(f"/products/{product}/delete", follow_redirects=True).get_data(as_text=True)
        assert "Deactivate it instead" in page
        assert _exists(make, Product, product)


def test_product_without_references_can_be_deleted(make, client_for):
    product = make.product(stock=0)
    assert make.movement_count(product) == 0  # zero opening stock writes no movement
    client_for(make.admin()).post(f"/products/{product}/delete")
    assert not _exists(make, Product, product)


def test_product_code_must_be_unique_case_insensitive(make, client_for):
    make.product(code="PRD-001")
    admin = client_for(make.admin())
    response = admin.post("/products/new", data={"product_code": "  prd-001 ", "name": "Copy", "category": "X",
                                                 "price": "10", "stock_quantity": "0", "is_active": "on"})
    assert response.status_code == 400
    assert "already exists" in response.get_data(as_text=True)


def test_product_codes_are_normalised(make, client_for):
    client_for(make.admin()).post("/products/new", data={"product_code": " abc-9 ", "name": "Thing", "category": "X",
                                                         "price": "10.50", "stock_quantity": "3", "is_active": "on"})
    code, price = make.run(lambda: db.session.execute(db.select(Product.product_code, Product.price)).one())
    assert code == "ABC-9" and str(price) == "10.50"


def test_negative_price_and_stock_rejected(make, client_for):
    admin = client_for(make.admin())
    for price, stock in (("-1", "0"), ("10", "-5"), ("abc", "0"), ("10", "1.5")):
        response = admin.post("/products/new", data={"product_code": "NEG-1", "name": "N", "category": "X",
                                                     "price": price, "stock_quantity": stock})
        assert response.status_code == 400
    assert make.count(Product) == 0


def test_opening_stock_is_recorded_as_movement(make):
    product = make.product(stock=12)
    movement = make.run(lambda: db.session.execute(
        db.select(StockMovement.movement_type, StockMovement.quantity_change)
        .where(StockMovement.product_id == product)).one())
    assert tuple(movement) == ("OPENING_STOCK", 12)


def test_stock_adjustment_requires_reason_and_rejects_negative_result(make, client_for):
    product = make.product(stock=5)
    admin = client_for(make.admin())
    admin.post(f"/products/{product}/adjust", data={"quantity_change": "3", "reason": "  "})
    assert make.stock(product) == 5                       # reason missing
    admin.post(f"/products/{product}/adjust", data={"quantity_change": "-6", "reason": "Damaged"})
    assert make.stock(product) == 5                       # would go negative
    admin.post(f"/products/{product}/adjust", data={"quantity_change": "0", "reason": "No-op"})
    assert make.stock(product) == 5                       # zero change rejected
    admin.post(f"/products/{product}/adjust", data={"quantity_change": "-5", "reason": "Damaged in transit"})
    assert make.stock(product) == 0
    admin.post(f"/products/{product}/adjust", data={"quantity_change": "+7", "reason": "Recount"})
    assert make.stock(product) == 7
    assert make.movement_count(product) == 3              # opening + 2 adjustments


def test_editing_a_product_cannot_change_stock(make, client_for):
    product = make.product(stock=5, code="ED-1")
    client_for(make.admin()).post(f"/products/{product}/edit", data={
        "product_code": "ED-1", "name": "Renamed", "category": "X", "price": "20", "stock_quantity": "999",
        "is_active": "on"})
    assert make.stock(product) == 5


def test_stock_always_equals_sum_of_movements(make, client_for):
    admin_id = make.admin()
    admin = client_for(admin_id)
    product = make.product(stock=20)
    customer = make.customer()
    first = make.order(admin_id, customer, [(product, 5)])
    second = make.order(admin_id, customer, [(product, 3)])
    admin.post(f"/api/orders/{first}/confirm")
    admin.post(f"/api/orders/{second}/confirm")
    admin.post(f"/api/orders/{first}/cancel")
    admin.post(f"/products/{product}/adjust", data={"quantity_change": "-2", "reason": "Breakage"})
    ledger = make.run(lambda: db.session.execute(
        db.select(db.func.sum(StockMovement.quantity_change)).where(StockMovement.product_id == product)).scalar())
    assert make.stock(product) == ledger == 15


def test_customer_search_and_status_filter(make, client_for):
    make.customer(name="Alpha Traders")
    make.customer(name="Beta Stores", active=False)
    admin = client_for(make.admin())
    page = admin.get("/customers?q=alpha").get_data(as_text=True)
    assert "Alpha Traders" in page and "Beta Stores" not in page
    page = admin.get("/customers?status=inactive").get_data(as_text=True)
    assert "Beta Stores" in page and "Alpha Traders" not in page


def test_customer_validation(make, client_for):
    response = client_for(make.admin()).post("/customers/new", data={"name": "", "email": "not-an-email",
                                                                     "mobile": "12", "city": ""})
    assert response.status_code == 400
    assert make.count(Customer) == 0
