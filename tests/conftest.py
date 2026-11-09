"""Test fixtures.

Tests run against a real MySQL database (TEST_DATABASE_URL), because SELECT ... FOR UPDATE,
CHECK constraints and collation rules are what we want to prove; SQLite would silently
ignore the row locks.

Data is committed (not wrapped in a rolled-back transaction) so that the concurrency
tests can see it from several connections. Every table is emptied after each test.

The test body does NOT keep an application context open: HTTP requests get their own
context (and their own Flask-Login user), and helpers below open a short context for
setup and assertions.
"""
import itertools

import pytest
from sqlalchemy import text

from app import create_app
from app.cli import run_schema
from app.config import TestConfig
from app.extensions import db
from app.models import ROLE_ADMIN, ROLE_SALES, Product, SalesOrder, StockMovement, User
from app.services import catalog, orders

TABLES_CHILD_FIRST = ["stock_movements", "sales_order_items", "sales_orders", "products", "customers", "users"]
_counter = itertools.count(1)


@pytest.fixture(scope="session")
def app():
    application = create_app(TestConfig)
    assert "test" in application.config["SQLALCHEMY_DATABASE_URI"], "Refusing to run tests on a non-test database"
    with application.app_context():
        run_schema()
    return application


@pytest.fixture(autouse=True)
def clean_tables(app):
    yield
    with app.app_context():
        db.session.remove()
        for table in TABLES_CHILD_FIRST:
            db.session.execute(text(f"DELETE FROM {table}"))
        db.session.commit()


class Factory:
    """Creates committed test data and returns ids (never ORM objects across contexts)."""

    def __init__(self, app):
        self.app = app

    def run(self, fn):
        """Run fn() inside a fresh app context and return its result."""
        with self.app.app_context():
            return fn()

    def user(self, role=ROLE_SALES, name=None):
        n = next(_counter)

        def make():
            user = User(name=name or f"User {n}", email=f"user{n}@test.example",
                        password_hash="pbkdf2:sha256:1000$x$y", role=role)
            db.session.add(user)
            db.session.commit()
            return user.id

        return self.run(make)

    def admin(self):
        return self.user(role=ROLE_ADMIN, name="Admin")

    def customer(self, active=True, name=None):
        n = next(_counter)
        return self.run(lambda: catalog.create_customer({
            "name": name or f"Customer {n}", "email": f"c{n}@test.example",
            "mobile": "9876543210", "city": "Nagpur", "is_active": active,
        }).id)

    def product(self, stock=10, price="100.00", active=True, code=None, category="General", by=None):
        n = next(_counter)
        owner = by or self._any_admin()
        return self.run(lambda: catalog.create_product({
            "product_code": code or f"P-{n:04d}", "name": f"Product {n}", "category": category,
            "price": price, "stock_quantity": stock, "is_active": active,
        }, db.session.get(User, owner)).id)

    def _any_admin(self):
        existing = self.run(lambda: db.session.execute(
            db.select(User.id).where(User.role == ROLE_ADMIN).limit(1)).scalar())
        return existing or self.admin()

    def order(self, user_id, customer_id, items, discount="0"):
        """items: [(product_id, quantity), ...] -> Draft order id"""
        payload = {"customer_id": customer_id, "discount_percentage": discount,
                   "items": [{"product_id": p, "quantity": q} for p, q in items]}
        return self.run(lambda: orders.create_draft(db.session.get(User, user_id), payload).id)

    # ---- read helpers for assertions (fresh context = fresh data)
    def stock(self, product_id):
        return self.run(lambda: db.session.get(Product, product_id).stock_quantity)

    def status(self, order_id):
        return self.run(lambda: db.session.get(SalesOrder, order_id).status)

    def movement_count(self, product_id=None):
        def count():
            query = db.select(db.func.count(StockMovement.id))
            if product_id is not None:
                query = query.where(StockMovement.product_id == product_id)
            return db.session.execute(query).scalar()
        return self.run(count)

    def count(self, model):
        return self.run(lambda: db.session.execute(db.select(db.func.count()).select_from(model)).scalar())


@pytest.fixture
def make(app):
    return Factory(app)


@pytest.fixture
def client_for(app):
    """client_for(user_id) -> a test client logged in as that user."""

    def build(user_id=None):
        client = app.test_client()
        if user_id is not None:
            with client.session_transaction() as session:
                session["_user_id"] = str(user_id)
                session["_fresh"] = True
        return client

    return build


@pytest.fixture
def call_as(make):
    """call_as(user_id, service_fn, *args) runs a service function as that user."""

    def call(user_id, fn, *args, **kwargs):
        def run():
            result = fn(db.session.get(User, user_id), *args, **kwargs)
            return result.to_dict() if hasattr(result, "to_dict") else result
        return make.run(run)

    return call
