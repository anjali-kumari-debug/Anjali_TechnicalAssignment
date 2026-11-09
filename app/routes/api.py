"""JSON REST API. Every endpoint requires login; permissions and validation come from the
same service functions the HTML pages use."""
from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required

from ..extensions import db
from ..permissions import get_order_for_user
from ..services import catalog, orders

api_bp = Blueprint("api", __name__)


def _page_args():
    try:
        page = max(int(request.args.get("page", 1)), 1)
        per_page = int(request.args.get("per_page", 20))
    except ValueError:
        page, per_page = 1, 20
    per_page = min(max(per_page, 1), current_app.config["API_MAX_PER_PAGE"])
    return page, per_page


def _page_body(pagination, items):
    return {
        "items": items,
        "page": pagination.page,
        "per_page": pagination.per_page,
        "total": pagination.total,
        "pages": pagination.pages,
    }


@api_bp.get("/products")
@login_required
def list_products():
    """Active products, with ?q= (code or name), ?category=, ?page=, ?per_page= (max 100)."""
    page, per_page = _page_args()
    query = catalog.search_products(q=request.args.get("q"), category=request.args.get("category"), active_only=True)
    pagination = db.paginate(query, page=page, per_page=per_page, error_out=False)
    return jsonify(_page_body(pagination, [p.to_dict() for p in pagination.items]))


@api_bp.get("/orders")
@login_required
def list_orders():
    """Orders visible to the current user (Sales Users: only their own)."""
    page, per_page = _page_args()
    query = orders.list_orders_query(current_user, status=request.args.get("status"), q=request.args.get("q"))
    pagination = db.paginate(query, page=page, per_page=per_page, error_out=False)
    return jsonify(_page_body(pagination, [o.to_dict(include_items=False) for o in pagination.items]))


@api_bp.post("/orders")
@login_required
def create_order():
    order = orders.create_draft(current_user, request.get_json())
    return jsonify(order.to_dict()), 201


@api_bp.get("/orders/<int:order_id>")
@login_required
def get_order(order_id):
    return jsonify(get_order_for_user(order_id, current_user).to_dict())


@api_bp.put("/orders/<int:order_id>")
@login_required
def update_order(order_id):
    order = orders.update_draft(current_user, order_id, request.get_json())
    return jsonify(order.to_dict())


@api_bp.post("/orders/<int:order_id>/confirm")
@login_required
def confirm_order(order_id):
    return jsonify(orders.confirm_order(current_user, order_id).to_dict())


@api_bp.post("/orders/<int:order_id>/cancel")
@login_required
def cancel_order(order_id):
    return jsonify(orders.cancel_order(current_user, order_id).to_dict())
