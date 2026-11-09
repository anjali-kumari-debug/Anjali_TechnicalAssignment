"""Login and logout (session cookie via Flask-Login)."""
from urllib.parse import urlsplit

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db
from ..models import User

auth_bp = Blueprint("auth", __name__)


# Checked against when the email is unknown, so a wrong email takes as long as a wrong
# password and response times do not reveal which emails have accounts.
_DUMMY_HASH = generate_password_hash("not-a-real-password")


def _safe_next(target):
    """Only allow redirects to paths on this site (prevents open-redirect via ?next=).
    Browsers treat '\\' like '/', so '/\\evil.example' would leave the site: reject it."""
    if (
        target
        and target.startswith("/")
        and not target.startswith("//")
        and "\\" not in target
        and not any(ord(ch) < 32 for ch in target)
        and urlsplit(target).netloc == ""
        and urlsplit(target).scheme == ""
    ):
        return target
    return url_for("web.index")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("web.index"))
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        user = db.session.execute(db.select(User).where(User.email == email)).scalar_one_or_none()
        password_ok = check_password_hash(user.password_hash if user else _DUMMY_HASH, password)
        if user is None or not password_ok:
            flash("Invalid email or password.", "error")  # same message either way: no user enumeration
            return render_template("login.html", email=email), 401
        login_user(user)
        return redirect(_safe_next(request.args.get("next")))
    return render_template("login.html")


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))
