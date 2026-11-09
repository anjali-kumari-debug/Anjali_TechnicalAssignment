"""HTML pages. Master data uses ordinary form posts; order pages use fetch() + the JSON API.
Both call the same service functions, so rules are enforced in one place."""
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ..errors import Conflict, ValidationError
from ..extensions import db
from ..models import ORDER_STATUSES, StockMovement
from ..permissions import admin_required, get_order_for_user
from ..services import catalog, csv_import, orders, reports, stock

web_bp = Blueprint("web", __name__)
PER_PAGE = 20


def _page():
    try:
        return max(int(request.args.get("page", 1)), 1)
    except ValueError:
        return 1


def _form_data():
    """request.form as a dict. Unchecked checkboxes are absent from a form post, so
    is_active is set explicitly."""
    data = request.form.to_dict()
    data["is_active"] = "is_active" in request.form
    return data


def _field_errors(err):
    return {d["field"]: d["message"] for d in (err.details or []) if "field" in d}


@web_bp.route("/")
@login_required
def index():
    return redirect(url_for("web.order_list"))


# ---------------------------------------------------------------- customers

@web_bp.route("/customers")
@login_required
def customer_list():
    status = request.args.get("status") if current_user.is_admin else "active"
    query = catalog.search_customers(q=request.args.get("q"), status=status, active_only=not current_user.is_admin)
    pagination = db.paginate(query, page=_page(), per_page=PER_PAGE, error_out=False)
    return render_template("customers/list.html", pagination=pagination, status=status)


@web_bp.route("/customers/new", methods=["GET", "POST"])
@admin_required
def customer_new():
    if request.method == "POST":
        try:
            customer = catalog.create_customer(_form_data())
        except ValidationError as err:
            return render_template("customers/form.html", customer=None, form=request.form,
                                   errors=_field_errors(err)), 400
        flash(f"Customer '{customer.name}' created.", "success")
        return redirect(url_for("web.customer_list"))
    return render_template("customers/form.html", customer=None, form={"is_active": True}, errors={})


@web_bp.route("/customers/<int:customer_id>/edit", methods=["GET", "POST"])
@admin_required
def customer_edit(customer_id):
    customer = catalog.get_customer(customer_id)
    if request.method == "POST":
        try:
            catalog.update_customer(customer_id, _form_data())
        except ValidationError as err:
            return render_template("customers/form.html", customer=customer, form=request.form,
                                   errors=_field_errors(err)), 400
        flash("Customer updated.", "success")
        return redirect(url_for("web.customer_list"))
    return render_template("customers/form.html", customer=customer, form=customer.to_dict(), errors={})


@web_bp.route("/customers/<int:customer_id>/delete", methods=["POST"])
@admin_required
def customer_delete(customer_id):
    try:
        catalog.delete_customer(customer_id)
        flash("Customer deleted.", "success")
    except Conflict as err:
        flash(err.message, "error")
    return redirect(url_for("web.customer_list"))


# ---------------------------------------------------------------- products

@web_bp.route("/products")
@login_required
def product_list():
    status = request.args.get("status") if current_user.is_admin else "active"
    query = catalog.search_products(q=request.args.get("q"), category=request.args.get("category"),
                                    status=status, active_only=not current_user.is_admin)
    pagination = db.paginate(query, page=_page(), per_page=PER_PAGE, error_out=False)
    return render_template("products/list.html", pagination=pagination, status=status,
                           categories=catalog.product_categories(active_only=not current_user.is_admin))


@web_bp.route("/products/new", methods=["GET", "POST"])
@admin_required
def product_new():
    if request.method == "POST":
        try:
            product = catalog.create_product(_form_data(), current_user)
        except ValidationError as err:
            return render_template("products/form.html", product=None, form=request.form,
                                   errors=_field_errors(err)), 400
        flash(f"Product {product.product_code} created.", "success")
        return redirect(url_for("web.product_detail", product_id=product.id))
    return render_template("products/form.html", product=None, form={"is_active": True}, errors={})


@web_bp.route("/products/import", methods=["GET", "POST"])
@admin_required
def product_import():
    if request.method == "POST":
        upload = request.files.get("file")
        if upload is None or not upload.filename:
            return render_template("products/import.html", columns=csv_import.COLUMNS,
                                   message="Choose a CSV file to upload.", errors=[]), 400
        try:
            count = csv_import.import_products(upload, current_user)
        except ValidationError as err:
            return render_template("products/import.html", columns=csv_import.COLUMNS,
                                   message=err.message, errors=err.details or []), 400
        flash(f"Imported {count} product(s).", "success")
        return redirect(url_for("web.product_list"))
    return render_template("products/import.html", columns=csv_import.COLUMNS, message=None, errors=[])


@web_bp.route("/products/<int:product_id>")
@admin_required
def product_detail(product_id):
    product = catalog.get_product(product_id)
    movements = db.session.execute(
        db.select(StockMovement).where(StockMovement.product_id == product_id)
        .order_by(StockMovement.created_at.desc(), StockMovement.id.desc()).limit(50)
    ).scalars().all()
    return render_template("products/detail.html", product=product, movements=movements, errors={}, form={})


@web_bp.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
@admin_required
def product_edit(product_id):
    product = catalog.get_product(product_id)
    if request.method == "POST":
        try:
            catalog.update_product(product_id, _form_data())
        except ValidationError as err:
            return render_template("products/form.html", product=product, form=request.form,
                                   errors=_field_errors(err)), 400
        flash("Product updated.", "success")
        return redirect(url_for("web.product_detail", product_id=product_id))
    return render_template("products/form.html", product=product, form=product.to_dict(), errors={})


@web_bp.route("/products/<int:product_id>/adjust", methods=["POST"])
@admin_required
def product_adjust(product_id):
    try:
        product = stock.adjust_stock(current_user, product_id, request.form.get("quantity_change"),
                                     request.form.get("reason"))
        flash(f"Stock updated. {product.product_code} now has {product.stock_quantity} units.", "success")
    except (ValidationError, Conflict) as err:
        messages = [d["message"] for d in (err.details or [])] or [err.message]
        for message in messages:
            flash(message, "error")
    return redirect(url_for("web.product_detail", product_id=product_id))


@web_bp.route("/products/<int:product_id>/delete", methods=["POST"])
@admin_required
def product_delete(product_id):
    try:
        catalog.delete_product(product_id)
        flash("Product deleted.", "success")
        return redirect(url_for("web.product_list"))
    except Conflict as err:
        flash(err.message, "error")
        return redirect(url_for("web.product_detail", product_id=product_id))


# ---------------------------------------------------------------- orders

@web_bp.route("/orders")
@login_required
def order_list():
    status = request.args.get("status")
    query = orders.list_orders_query(current_user, status=status, q=request.args.get("q"))
    pagination = db.paginate(query, page=_page(), per_page=PER_PAGE, error_out=False)
    return render_template("orders/list.html", pagination=pagination, status=status, statuses=ORDER_STATUSES)


def _active_customers():
    return db.session.execute(catalog.search_customers(active_only=True)).scalars().all()


@web_bp.route("/orders/new")
@login_required
def order_new():
    return render_template("orders/form.html", order=None, customers=_active_customers())


@web_bp.route("/orders/<int:order_id>")
@login_required
def order_detail(order_id):
    order = get_order_for_user(order_id, current_user)
    return render_template("orders/detail.html", order=order)


@web_bp.route("/orders/<int:order_id>/edit")
@login_required
def order_edit(order_id):
    order = get_order_for_user(order_id, current_user)
    if not order.is_draft:
        flash(f"Order {order.order_number} is {order.status} and is read-only.", "error")
        return redirect(url_for("web.order_detail", order_id=order_id))
    return render_template("orders/form.html", order=order, customers=_active_customers())


# ---------------------------------------------------------------- reports (Admin only)

@web_bp.route("/reports/customer-sales")
@admin_required
def report_customer_sales():
    try:
        rows, date_from, date_to = reports.customer_sales_summary(request.args.get("date_from"),
                                                                  request.args.get("date_to"))
        error = None
    except ValidationError as err:
        rows, date_from, date_to = [], request.args.get("date_from"), request.args.get("date_to")
        error = "; ".join(d["message"] for d in err.details or []) or err.message
    return render_template("reports/customer_sales.html", rows=rows, date_from=date_from, date_to=date_to,
                           error=error)


@web_bp.route("/reports/product-sales")
@admin_required
def report_product_sales():
    return render_template("reports/product_sales.html", rows=reports.product_sales_summary())


@web_bp.route("/reports/low-stock")
@admin_required
def report_low_stock():
    raw = request.args.get("threshold", "5")
    try:
        rows, threshold = reports.low_stock(raw)
        error = None
    except ValidationError as err:
        rows, threshold, error = [], raw, err.details[0]["message"]
    return render_template("reports/low_stock.html", rows=rows, threshold=threshold, error=error)


@web_bp.route("/reports/stock-movements")
@admin_required
def report_stock_movements():
    product_id = request.args.get("product_id", type=int)
    products = db.session.execute(catalog.search_products()).scalars().all()
    return render_template("reports/stock_movements.html", rows=reports.stock_movement_history(product_id),
                           products=products, product_id=product_id)
