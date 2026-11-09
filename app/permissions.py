"""Role and ownership checks. All permission rules live here so they are applied the same
way by HTML pages and by the JSON API."""
from functools import wraps

from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload

from .errors import Forbidden, NotFound
from .extensions import db
from .models import SalesOrder


def admin_required(view):
    """Allow only logged-in Admin users. Sales Users get 403, anonymous users get 401/redirect."""

    @wraps(view)
    @login_required
    def wrapper(*args, **kwargs):
        if not current_user.is_admin:
            raise Forbidden("Access denied. Only Admin users can do this.")
        return view(*args, **kwargs)

    return wrapper


def get_order_for_user(order_id, user, lock=False):
    """Return the order if `user` may access it.

    * Missing order          -> 404
    * Another user's order   -> 403 (Admins may access every order)
    * lock=True              -> re-read the order *and its items* with SELECT ... FOR UPDATE

    The ownership check is done with a plain read *before* locking, so a Sales User
    cannot hold locks on orders that belong to someone else.

    populate_existing=True matters: without it SQLAlchemy would hand back the object
    already in the session (loaded by the plain read) with its *old* status, even
    though the locked SELECT read fresh data. A second "confirm" that waited on the
    lock would then still see 'Draft' and deduct stock twice.

    The items are loaded in the same locking SELECT (a JOIN). A later plain lazy-load
    would read from the transaction's older snapshot and could miss an edit that was
    committed while we were waiting for the lock.
    """
    order = db.session.get(SalesOrder, order_id)
    if order is None:
        raise NotFound(f"Order {order_id} was not found.")
    if not user.is_admin and order.created_by != user.id:
        raise Forbidden("Access denied. You can only access your own orders.")
    if lock:
        order = db.session.execute(
            db.select(SalesOrder)
            .options(joinedload(SalesOrder.items))
            .where(SalesOrder.id == order_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).unique().scalar_one()
    return order
