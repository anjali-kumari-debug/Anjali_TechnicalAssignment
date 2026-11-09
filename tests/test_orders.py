"""Order lifecycle through the REST API (assignment Parts 5, 6, 8, 12)."""
from app.extensions import db
from app.models import Product


def _setup(make, stock=(10, 10)):
    user = make.user()
    customer = make.customer()
    products = [make.product(stock=s, price=price) for s, price in zip(stock, ("1500.00", "500.00"))]
    return user, customer, products


def test_create_order_calculates_totals_on_server(make, client_for):
    user, customer, (keyboard, mouse) = _setup(make)
    response = client_for(user).post("/api/orders", json={
        "customer_id": customer, "discount_percentage": "10",
        # Rates, totals and status from the browser must be ignored:
        "subtotal": "1.00", "grand_total": "1.00", "status": "Confirmed", "created_by": 999,
        "items": [{"product_id": keyboard, "quantity": 2, "rate": "1.00", "amount": "1.00"},
                  {"product_id": mouse, "quantity": 3}],
    })
    assert response.status_code == 201
    order = response.get_json()
    assert order["status"] == "Draft"
    assert order["created_by"]["id"] == user
    assert [i["rate"] for i in order["items"]] == ["1500.00", "500.00"]
    assert (order["subtotal"], order["discount_amount"], order["grand_total"]) == ("4500.00", "450.00", "4050.00")
    assert order["order_number"].startswith("SO-")
    assert make.stock(keyboard) == 10  # Draft does not reserve stock


def test_order_validation_errors(make, client_for):
    user, customer, (p1, _) = _setup(make)
    inactive_customer = make.customer(active=False)
    inactive_product = make.product(active=False)
    client = client_for(user)
    cases = [
        ({"customer_id": customer, "items": []}, "items"),
        ({"customer_id": customer, "items": [{"product_id": p1, "quantity": 0}]}, "items[0].quantity"),
        ({"customer_id": customer, "items": [{"product_id": p1, "quantity": -2}]}, "items[0].quantity"),
        ({"customer_id": customer, "items": [{"product_id": p1, "quantity": 1.5}]}, "items[0].quantity"),
        ({"customer_id": customer, "discount_percentage": "20.01", "items": [{"product_id": p1, "quantity": 1}]},
         "discount_percentage"),
        ({"customer_id": customer, "discount_percentage": -1, "items": [{"product_id": p1, "quantity": 1}]},
         "discount_percentage"),
        ({"customer_id": customer, "items": [{"product_id": p1, "quantity": 1}, {"product_id": p1, "quantity": 2}]},
         "items[1].product_id"),
        ({"customer_id": inactive_customer, "items": [{"product_id": p1, "quantity": 1}]}, "customer_id"),
        ({"customer_id": customer, "items": [{"product_id": inactive_product, "quantity": 1}]}, "items[0].product_id"),
        ({"customer_id": customer, "items": [{"product_id": 999999, "quantity": 1}]}, "items[0].product_id"),
    ]
    for payload, field in cases:
        response = client.post("/api/orders", json=payload)
        assert response.status_code == 400, payload
        fields = [d["field"] for d in response.get_json()["error"]["details"]]
        assert field in fields, (payload, fields)
    assert make.count(db.Model.metadata.tables["sales_orders"]) == 0


def test_edit_draft_keeps_stored_rate_and_replaces_lines(make, client_for):
    user, customer, (keyboard, mouse) = _setup(make)
    extra = make.product(price="250.00")
    order_id = make.order(user, customer, [(keyboard, 1), (mouse, 1)])
    # The price changes after the order was created...
    make.run(lambda: (setattr(db.session.get(Product, keyboard), "price", 9999), db.session.commit()))

    response = client_for(user).put(f"/api/orders/{order_id}", json={
        "customer_id": customer, "discount_percentage": "0",
        "items": [{"product_id": keyboard, "quantity": 3}, {"product_id": extra, "quantity": 2}],  # mouse removed
    })
    assert response.status_code == 200
    items = {i["product_id"]: i for i in response.get_json()["items"]}
    assert set(items) == {keyboard, extra}
    assert items[keyboard]["rate"] == "1500.00"   # stored rate kept
    assert items[keyboard]["amount"] == "4500.00"
    assert items[extra]["rate"] == "250.00"       # new line uses current price
    assert response.get_json()["subtotal"] == "5000.00"


def test_confirm_with_sufficient_stock_deducts_and_records_movements(make, client_for):
    user, customer, (keyboard, mouse) = _setup(make, stock=(5, 10))
    order_id = make.order(user, customer, [(keyboard, 2), (mouse, 3)])
    before = make.movement_count()

    response = client_for(user).post(f"/api/orders/{order_id}/confirm")
    assert response.status_code == 200
    assert response.get_json()["status"] == "Confirmed"
    assert make.stock(keyboard) == 3 and make.stock(mouse) == 7
    assert make.movement_count() == before + 2


def test_confirm_with_one_insufficient_item_changes_nothing(make, client_for):
    user, customer, (keyboard, mouse) = _setup(make, stock=(5, 1))
    order_id = make.order(user, customer, [(keyboard, 2), (mouse, 3)])
    before = make.movement_count()

    response = client_for(user).post(f"/api/orders/{order_id}/confirm")
    assert response.status_code == 409
    error = response.get_json()["error"]
    assert error["code"] == "INSUFFICIENT_STOCK"
    assert error["details"][0]["requested"] == 3 and error["details"][0]["available"] == 1
    assert make.stock(keyboard) == 5 and make.stock(mouse) == 1  # keyboard NOT partly deducted
    assert make.status(order_id) == "Draft"
    assert make.movement_count() == before


def test_repeated_confirmation_does_not_deduct_again(make, client_for):
    user, customer, (keyboard, _) = _setup(make, stock=(10, 10))
    order_id = make.order(user, customer, [(keyboard, 4)])
    client = client_for(user)
    assert client.post(f"/api/orders/{order_id}/confirm").status_code == 200
    movements = make.movement_count()

    second = client.post(f"/api/orders/{order_id}/confirm")
    assert second.status_code == 409
    assert second.get_json()["error"]["code"] == "ORDER_NOT_DRAFT"
    assert make.stock(keyboard) == 6
    assert make.movement_count() == movements


def test_cancel_confirmed_order_restores_stock_once(make, client_for):
    user, customer, (keyboard, mouse) = _setup(make, stock=(10, 10))
    order_id = make.order(user, customer, [(keyboard, 4), (mouse, 1)])
    client = client_for(user)
    client.post(f"/api/orders/{order_id}/confirm")
    assert make.stock(keyboard) == 6

    assert client.post(f"/api/orders/{order_id}/cancel").status_code == 200
    assert make.stock(keyboard) == 10 and make.stock(mouse) == 10
    movements = make.movement_count()

    again = client.post(f"/api/orders/{order_id}/cancel")
    assert again.status_code == 409
    assert make.stock(keyboard) == 10           # not restored twice
    assert make.movement_count() == movements
    assert make.status(order_id) == "Cancelled"


def test_cancel_draft_has_no_stock_effect(make, client_for):
    user, customer, (keyboard, _) = _setup(make)
    order_id = make.order(user, customer, [(keyboard, 4)])
    before = make.movement_count()
    assert client_for(user).post(f"/api/orders/{order_id}/cancel").status_code == 200
    assert make.stock(keyboard) == 10
    assert make.movement_count() == before


def test_confirmed_and_cancelled_orders_are_read_only(make, client_for):
    user, customer, (keyboard, _) = _setup(make)
    client = client_for(user)
    confirmed = make.order(user, customer, [(keyboard, 1)])
    client.post(f"/api/orders/{confirmed}/confirm")
    cancelled = make.order(user, customer, [(keyboard, 1)])
    client.post(f"/api/orders/{cancelled}/cancel")
    edit = {"customer_id": customer, "items": [{"product_id": keyboard, "quantity": 5}]}
    for order_id in (confirmed, cancelled):
        response = client.put(f"/api/orders/{order_id}", json=edit)
        assert response.status_code == 409
        assert response.get_json()["error"]["code"] == "ORDER_NOT_DRAFT"
    assert client.post(f"/api/orders/{cancelled}/confirm").status_code == 409


def test_confirm_rejected_if_product_deactivated_after_draft(make, client_for):
    user, customer, (keyboard, _) = _setup(make)
    order_id = make.order(user, customer, [(keyboard, 1)])
    make.run(lambda: (setattr(db.session.get(Product, keyboard), "is_active", False), db.session.commit()))
    response = client_for(user).post(f"/api/orders/{order_id}/confirm")
    assert response.status_code == 409
    assert make.stock(keyboard) == 10 and make.status(order_id) == "Draft"


def test_order_numbers_are_unique(make, client_for):
    user, customer, (keyboard, _) = _setup(make)
    numbers = {client_for(user).post("/api/orders", json={
        "customer_id": customer, "items": [{"product_id": keyboard, "quantity": 1}]}).get_json()["order_number"]
        for _ in range(5)}
    assert len(numbers) == 5
