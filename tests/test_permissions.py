"""Authentication, roles and ownership (assignment Part 2, Part 12)."""
import pytest


@pytest.fixture
def two_sales_users(make):
    owner, other = make.user(), make.user()
    customer = make.customer()
    product = make.product(stock=10)
    order_id = make.order(owner, customer, [(product, 2)])
    return owner, other, customer, product, order_id


def test_sales_user_cannot_access_another_users_order(make, client_for, two_sales_users):
    owner, other, customer, product, order_id = two_sales_users
    intruder = client_for(other)
    edit = {"customer_id": customer, "items": [{"product_id": product, "quantity": 9}]}
    attempts = [
        intruder.get(f"/api/orders/{order_id}"),
        intruder.put(f"/api/orders/{order_id}", json=edit),
        intruder.post(f"/api/orders/{order_id}/confirm"),
        intruder.post(f"/api/orders/{order_id}/cancel"),
    ]
    for response in attempts:
        assert response.status_code == 403
        assert response.get_json()["error"]["code"] == "FORBIDDEN"
    assert intruder.get(f"/orders/{order_id}").status_code == 403
    assert intruder.get(f"/orders/{order_id}/edit").status_code == 403
    # Nothing changed:
    assert make.status(order_id) == "Draft" and make.stock(product) == 10
    # The owner still has access:
    assert client_for(owner).get(f"/api/orders/{order_id}").status_code == 200


def test_admin_can_access_and_manage_any_order(make, client_for, two_sales_users):
    *_, product, order_id = two_sales_users
    admin = client_for(make.admin())
    assert admin.get(f"/api/orders/{order_id}").status_code == 200
    assert admin.post(f"/api/orders/{order_id}/confirm").status_code == 200
    assert make.stock(product) == 8


def test_order_lists_only_show_own_orders_to_sales_users(make, client_for, two_sales_users):
    owner, other, customer, product, order_id = two_sales_users
    other_order = make.order(other, customer, [(product, 1)])
    api_ids = {o["id"] for o in client_for(other).get("/api/orders").get_json()["items"]}
    assert api_ids == {other_order}
    page = client_for(other).get("/orders").get_data(as_text=True)
    assert f"/orders/{other_order}" in page and f"/orders/{order_id}\"" not in page
    admin_ids = {o["id"] for o in client_for(make.admin()).get("/api/orders").get_json()["items"]}
    assert admin_ids == {order_id, other_order}


def test_missing_order_is_404(make, client_for):
    response = client_for(make.user()).get("/api/orders/999999")
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "NOT_FOUND"


def test_unauthenticated_api_returns_401_json_not_redirect(client_for):
    anonymous = client_for(None)
    for method, url in [("get", "/api/products"), ("get", "/api/orders/1"), ("post", "/api/orders"),
                        ("post", "/api/orders/1/confirm")]:
        response = getattr(anonymous, method)(url, json={} if method == "post" else None)
        assert response.status_code == 401, url
        assert response.get_json()["error"]["code"] == "UNAUTHORIZED"


def test_unauthenticated_pages_redirect_to_login(client_for):
    response = client_for(None).get("/orders")
    assert response.status_code == 302 and "/login" in response.headers["Location"]


@pytest.mark.parametrize("method, url", [
    ("get", "/reports/customer-sales"), ("get", "/reports/product-sales"), ("get", "/reports/low-stock"),
    ("get", "/reports/stock-movements"), ("get", "/customers/new"), ("post", "/customers/new"),
    ("get", "/products/new"), ("post", "/products/new"),
])
def test_sales_user_cannot_use_admin_pages(make, client_for, method, url):
    assert getattr(client_for(make.user()), method)(url).status_code == 403


def test_sales_user_cannot_modify_master_data_or_stock(make, client_for):
    customer = make.customer()
    product = make.product(stock=10)
    sales = client_for(make.user())
    assert sales.post(f"/customers/{customer}/edit", data={"name": "Hacked"}).status_code == 403
    assert sales.post(f"/customers/{customer}/delete").status_code == 403
    assert sales.post(f"/products/{product}/edit", data={"name": "Hacked"}).status_code == 403
    assert sales.post(f"/products/{product}/delete").status_code == 403
    assert sales.post(f"/products/{product}/adjust", data={"quantity_change": "-10", "reason": "x"}).status_code == 403
    assert make.stock(product) == 10


def test_sales_user_sees_only_active_products_and_customers(make, client_for):
    active = make.product(code="ACT-1")
    make.product(code="OLD-1", active=False)
    make.customer(name="Live Customer")
    make.customer(name="Dormant Customer", active=False)
    sales = client_for(make.user())
    codes = [p["product_code"] for p in sales.get("/api/products").get_json()["items"]]
    assert codes == ["ACT-1"]
    page = sales.get("/customers?status=inactive").get_data(as_text=True)
    assert "Live Customer" in page and "Dormant Customer" not in page
    assert "OLD-1" not in sales.get("/products?status=inactive").get_data(as_text=True)
    assert active


def test_api_products_search_and_pagination(make, client_for):
    for i in range(1, 8):
        make.product(code=f"KB-{i:02d}")
    make.product(code="MS-01")
    client = client_for(make.user())
    body = client.get("/api/products?q=KB&per_page=3&page=2").get_json()
    assert body["total"] == 7 and body["pages"] == 3 and body["page"] == 2
    assert [p["product_code"] for p in body["items"]] == ["KB-04", "KB-05", "KB-06"]
    assert client.get("/api/products?per_page=5000").get_json()["per_page"] == 100  # capped
    assert "password_hash" not in client.get("/api/orders").get_data(as_text=True)


def test_login_and_logout(app, make, client_for):
    from werkzeug.security import generate_password_hash
    from app.extensions import db
    from app.models import User

    def make_login_user():
        user = User(name="Login Test", email="login@test.example", role="Admin",
                    password_hash=generate_password_hash("correct-horse", method="pbkdf2:sha256:1000"))
        db.session.add(user)
        db.session.commit()
    make.run(make_login_user)
    client = client_for(None)
    assert client.post("/login", data={"email": "login@test.example", "password": "wrong"}).status_code == 401
    assert client.post("/login", data={"email": "LOGIN@test.example", "password": "correct-horse"}).status_code == 302
    assert client.get("/api/products").status_code == 200
    client.post("/logout")
    assert client.get("/api/products").status_code == 401


def test_login_next_parameter_cannot_redirect_off_site(make, client_for):
    from werkzeug.security import generate_password_hash
    from app.extensions import db
    from app.models import User
    make.run(lambda: (db.session.add(User(name="N", email="n@test.example", role="Admin",
                      password_hash=generate_password_hash("pw-12345678", method="pbkdf2:sha256:1000"))),
                      db.session.commit()))
    response = client_for(None).post("/login?next=https://evil.example/x",
                                     data={"email": "n@test.example", "password": "pw-12345678"})
    assert response.headers["Location"] == "/"
