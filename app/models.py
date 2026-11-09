"""ORM models. They mirror db/schema.sql, which is the source of truth for the database."""
from datetime import date, datetime
from decimal import Decimal

from flask_login import UserMixin
from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .extensions import db

ROLE_ADMIN = "Admin"
ROLE_SALES = "Sales User"
ROLES = (ROLE_ADMIN, ROLE_SALES)

STATUS_DRAFT = "Draft"
STATUS_CONFIRMED = "Confirmed"
STATUS_CANCELLED = "Cancelled"
ORDER_STATUSES = (STATUS_DRAFT, STATUS_CONFIRMED, STATUS_CANCELLED)

MOVE_OPENING = "OPENING_STOCK"
MOVE_ORDER_CONFIRM = "ORDER_CONFIRM"
MOVE_ORDER_CANCEL = "ORDER_CANCEL"
MOVE_ADJUSTMENT = "ADJUSTMENT"
MOVEMENT_TYPES = (MOVE_OPENING, MOVE_ORDER_CONFIRM, MOVE_ORDER_CANCEL, MOVE_ADJUSTMENT)


def _money(value):
    """Decimal -> '1500.00' string for JSON (keeps exact value; JS parses to paise)."""
    return None if value is None else f"{value:.2f}"


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(150), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(Enum(*ROLES, name="user_role"), default=ROLE_SALES)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    def to_dict(self):
        # Never include password_hash.
        return {"id": self.id, "name": self.name, "email": self.email, "role": self.role}


class Customer(db.Model):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    email: Mapped[str] = mapped_column(String(150))
    mobile: Mapped[str] = mapped_column(String(20))
    city: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "mobile": self.mobile,
            "city": self.city,
            "is_active": self.is_active,
        }


class Product(db.Model):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(150))
    category: Mapped[str] = mapped_column(String(100))
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    stock_quantity: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    def to_dict(self):
        return {
            "id": self.id,
            "product_code": self.product_code,
            "name": self.name,
            "category": self.category,
            "price": _money(self.price),
            "stock_quantity": self.stock_quantity,
            "is_active": self.is_active,
        }


class SalesOrder(db.Model):
    __tablename__ = "sales_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_number: Mapped[str | None] = mapped_column(String(30), unique=True, nullable=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    order_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Enum(*ORDER_STATUSES, name="order_status"), default=STATUS_DRAFT)
    discount_percentage: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0.00"))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    grand_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    customer: Mapped[Customer] = relationship()
    creator: Mapped[User] = relationship()
    # Items belong to the order: removing an item from this list deletes the row.
    items: Mapped[list["SalesOrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="SalesOrderItem.id"
    )

    @property
    def is_draft(self) -> bool:
        return self.status == STATUS_DRAFT

    def to_dict(self, include_items=True):
        data = {
            "id": self.id,
            "order_number": self.order_number,
            "customer": {"id": self.customer.id, "name": self.customer.name},
            "order_date": self.order_date.isoformat(),
            "status": self.status,
            "discount_percentage": _money(self.discount_percentage),
            "subtotal": _money(self.subtotal),
            "discount_amount": _money(self.discount_amount),
            "grand_total": _money(self.grand_total),
            "created_by": {"id": self.creator.id, "name": self.creator.name},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if include_items:
            data["items"] = [item.to_dict() for item in self.items]
        return data


class SalesOrderItem(db.Model):
    __tablename__ = "sales_order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sales_order_id: Mapped[int] = mapped_column(ForeignKey("sales_orders.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    rate: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))

    order: Mapped[SalesOrder] = relationship(back_populates="items")
    product: Mapped[Product] = relationship()

    def to_dict(self):
        return {
            "id": self.id,
            "product_id": self.product_id,
            "product_code": self.product.product_code,
            "product_name": self.product.name,
            "quantity": self.quantity,
            "rate": _money(self.rate),
            "amount": _money(self.amount),
        }


class StockMovement(db.Model):
    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    movement_type: Mapped[str] = mapped_column(Enum(*MOVEMENT_TYPES, name="movement_type"))
    quantity_change: Mapped[int] = mapped_column(Integer)
    related_order_id: Mapped[int | None] = mapped_column(ForeignKey("sales_orders.id"), nullable=True)
    reason: Mapped[str] = mapped_column(String(255))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    product: Mapped[Product] = relationship()
    order: Mapped[SalesOrder | None] = relationship()
    creator: Mapped[User] = relationship()
