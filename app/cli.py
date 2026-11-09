"""Flask CLI commands:

    flask init-db        create all tables from db/schema.sql (drops existing tables!)
    flask seed           create sample users, customers, products and orders
    flask create-user    create one user interactively
"""
import os
import re
from pathlib import Path

import click
from sqlalchemy import text
from werkzeug.security import generate_password_hash

from .extensions import db
from .models import ROLE_ADMIN, ROLE_SALES, ROLES, User

SCHEMA_FILE = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


def schema_statements(path=SCHEMA_FILE):
    """Split schema.sql into single statements (PyMySQL runs one statement per call).
    Comment lines are removed first because they may contain ';'."""
    sql = re.sub(r"--[^\n]*", "", Path(path).read_text(encoding="utf-8"))
    return [statement.strip() for statement in sql.split(";") if statement.strip()]


def run_schema():
    with db.engine.begin() as conn:
        for statement in schema_statements():
            conn.execute(text(statement))


def hash_password(password):
    from flask import current_app

    return generate_password_hash(password, method=current_app.config["PASSWORD_HASH_METHOD"])


def create_user(name, email, password, role):
    if role not in ROLES:
        raise click.BadParameter(f"role must be one of {ROLES}")
    if len(password) < 8:
        raise click.BadParameter("password must be at least 8 characters")
    user = User(name=name, email=email.strip().lower(), password_hash=hash_password(password), role=role)
    db.session.add(user)
    db.session.commit()
    return user


def _backdate(order_id, months_back):
    from datetime import date

    from .models import SalesOrder

    order = db.session.get(SalesOrder, order_id)
    today = date.today()
    month = (today.month - months_back - 1) % 12 + 1
    year = today.year + (today.month - months_back - 1) // 12
    order.order_date = date(year, month, 15)
    order.order_number = f"SO-{order.order_date:%Y%m%d}-{order.id:05d}"
    db.session.commit()


def register_cli(app):
    @app.cli.command("init-db")
    @click.option("--yes", is_flag=True, help="Do not ask for confirmation.")
    def init_db(yes):
        """Drop and recreate all tables from db/schema.sql."""
        if not yes:
            click.confirm("This DROPS all tables in the configured database. Continue?", abort=True)
        run_schema()
        click.echo("Database schema created.")

    @app.cli.command("create-user")
    @click.option("--name", prompt=True)
    @click.option("--email", prompt=True)
    @click.option("--role", type=click.Choice(ROLES), prompt=True, default=ROLE_SALES)
    @click.password_option()
    def create_user_command(name, email, role, password):
        """Create a login account."""
        user = create_user(name, email, password, role)
        click.echo(f"Created {user.role} {user.email}")

    @app.cli.command("seed")
    def seed():
        """Create sample accounts and data. Passwords come from SEED_ADMIN_PASSWORD /
        SEED_SALES_PASSWORD in .env (no credentials are stored in the repository)."""
        from .services import catalog, orders

        admin_pw = os.environ.get("SEED_ADMIN_PASSWORD")
        sales_pw = os.environ.get("SEED_SALES_PASSWORD")
        if not admin_pw or not sales_pw:
            raise click.ClickException("Set SEED_ADMIN_PASSWORD and SEED_SALES_PASSWORD in .env first.")
        if db.session.execute(db.select(User.id).limit(1)).first():
            raise click.ClickException("Database already has users. Run `flask init-db` first for a clean seed.")

        admin = create_user("Asha Admin", "admin@example.com", admin_pw, ROLE_ADMIN)
        ravi = create_user("Ravi Sales", "ravi@example.com", sales_pw, ROLE_SALES)
        meera = create_user("Meera Sales", "meera@example.com", sales_pw, ROLE_SALES)

        customers = [
            catalog.create_customer(c) for c in [
                {"name": "Sharma Traders", "email": "accounts@sharmatraders.example", "mobile": "9876543210", "city": "Nagpur"},
                {"name": "Gupta Electronics", "email": "gupta@electronics.example", "mobile": "9812345678", "city": "Pune"},
                {"name": "Iyer & Sons", "email": "iyer.sons@example.com", "mobile": "+91 98450 11223", "city": "Chennai"},
                {"name": "Khan Stationers", "email": "khan.stationers@example.com", "mobile": "9900112233", "city": "Mumbai"},
                {"name": "Old Mill Supplies", "email": "oldmill@example.com", "mobile": "9000000001", "city": "Indore",
                 "is_active": False},
            ]
        ]
        products = [
            catalog.create_product(p, admin) for p in [
                {"product_code": "PRD-001", "name": "Keyboard", "category": "Accessories", "price": "1500", "stock_quantity": 20},
                {"product_code": "PRD-002", "name": "Mouse", "category": "Accessories", "price": "500", "stock_quantity": 50},
                {"product_code": "PRD-003", "name": "24in Monitor", "category": "Displays", "price": "11999.50", "stock_quantity": 8},
                {"product_code": "PRD-004", "name": "USB-C Hub", "category": "Accessories", "price": "2499", "stock_quantity": 3},
                {"product_code": "PRD-005", "name": "Laptop Stand", "category": "Furniture", "price": "1799", "stock_quantity": 0},
                {"product_code": "PRD-006", "name": "Old Webcam", "category": "Accessories", "price": "999", "stock_quantity": 5,
                 "is_active": False},
            ]
        ]
        keyboard, mouse, monitor, hub = products[0], products[1], products[2], products[3]

        # The worked example from the assignment: 2 x 1500 + 3 x 500, 10% discount = 4050.00
        example = orders.create_draft(ravi, {"customer_id": customers[0].id, "discount_percentage": "10", "items": [
            {"product_id": keyboard.id, "quantity": 2}, {"product_id": mouse.id, "quantity": 3}]})
        orders.confirm_order(ravi, example.id)
        orders.create_draft(ravi, {"customer_id": customers[1].id, "discount_percentage": "5", "items": [
            {"product_id": monitor.id, "quantity": 1}, {"product_id": hub.id, "quantity": 2}]})
        cancelled = orders.create_draft(meera, {"customer_id": customers[2].id, "items": [
            {"product_id": mouse.id, "quantity": 4}]})
        orders.confirm_order(meera, cancelled.id)
        orders.cancel_order(meera, cancelled.id)
        confirmed = orders.create_draft(meera, {"customer_id": customers[1].id, "discount_percentage": "2.5", "items": [
            {"product_id": monitor.id, "quantity": 2}]})
        orders.confirm_order(meera, confirmed.id)

        # Two older confirmed orders so the month-wise report has more than one month.
        # (Order dates are normally set by the server to "today"; back-dating is seed-only.)
        for months_back, customer, items in ((2, customers[3], [(keyboard, 1), (mouse, 2)]),
                                             (1, customers[0], [(mouse, 5)])):
            draft = orders.create_draft(admin, {"customer_id": customer.id, "items": [
                {"product_id": product.id, "quantity": qty} for product, qty in items]})
            _backdate(draft.id, months_back)  # before confirming, so movements show the final number
            orders.confirm_order(admin, draft.id)

        click.echo("Seeded sample data. Accounts (passwords from .env):")
        for user in (admin, ravi, meera):
            click.echo(f"  {user.role:<10} {user.email}")
