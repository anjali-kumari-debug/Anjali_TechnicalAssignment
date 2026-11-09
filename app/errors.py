"""Application errors and the handlers that turn them into JSON (API) or HTML (pages).

Services raise AppError subclasses; they never build HTTP responses themselves.
Every error body has the same shape:

    {"error": {"code": "INSUFFICIENT_STOCK", "message": "...", "details": [...]}}
"""
from flask import jsonify, render_template, request
from flask_login import current_user
from flask_wtf.csrf import CSRFError
from sqlalchemy.exc import DataError, IntegrityError, OperationalError
from werkzeug.exceptions import HTTPException

from .extensions import db

# MySQL error numbers for lock problems (see README, "Concurrency").
MYSQL_LOCK_WAIT_TIMEOUT = 1205
MYSQL_DEADLOCK = 1213


class AppError(Exception):
    status_code = 400
    code = "BAD_REQUEST"

    def __init__(self, message, details=None, code=None):
        super().__init__(message)
        self.message = message
        self.details = details
        if code:
            self.code = code


class ValidationError(AppError):
    """Invalid input. `details` is a list of {"field": ..., "message": ...}."""
    status_code = 400
    code = "VALIDATION_ERROR"


class Forbidden(AppError):
    status_code = 403
    code = "FORBIDDEN"


class NotFound(AppError):
    status_code = 404
    code = "NOT_FOUND"


class Conflict(AppError):
    """The request is valid but conflicts with current state (stock, status, references)."""
    status_code = 409
    code = "CONFLICT"


def wants_json() -> bool:
    return request.path.startswith("/api/") or request.is_json


def error_payload(code, message, details=None):
    body = {"code": code, "message": message}
    if details:
        body["details"] = details
    return {"error": body}


def _render(status, code, message, details=None):
    if wants_json():
        return jsonify(error_payload(code, message, details)), status
    return render_template("error.html", status=status, message=message, details=details), status


def register_error_handlers(app):
    @app.errorhandler(AppError)
    def handle_app_error(err):
        db.session.rollback()
        return _render(err.status_code, err.code, err.message, err.details)

    @app.errorhandler(CSRFError)
    def handle_csrf(err):
        # The CSRF check runs before @login_required; an anonymous API caller should
        # still be told to log in (401), not that a token is missing.
        if wants_json() and not current_user.is_authenticated:
            return _render(401, "UNAUTHORIZED", "Please log in to continue.")
        return _render(400, "CSRF_FAILED", "The security (CSRF) token is missing or expired. Reload the page and try again.")

    @app.errorhandler(OperationalError)
    def handle_operational(err):
        db.session.rollback()
        errno = err.orig.args[0] if err.orig is not None and err.orig.args else None
        if errno in (MYSQL_LOCK_WAIT_TIMEOUT, MYSQL_DEADLOCK):
            return _render(409, "BUSY", "Another user is updating the same stock right now. Please try again.")
        app.logger.exception("Database error")
        return _render(500, "INTERNAL_ERROR", "An unexpected error occurred.")

    @app.errorhandler(IntegrityError)
    def handle_integrity(err):
        # Backstop: services check references and duplicates first, but another user can
        # change the data between that check and our write. The database constraint wins.
        db.session.rollback()
        app.logger.warning("Integrity error: %s", err.orig)
        return _render(409, "CONFLICT", "The data was changed by another user while you were working. "
                                        "Reload the page and try again.")

    @app.errorhandler(DataError)
    def handle_data_error(err):
        db.session.rollback()
        app.logger.warning("Data error: %s", err.orig)
        return _render(400, "VALUE_OUT_OF_RANGE", "A value is too large or out of range.")

    @app.errorhandler(HTTPException)
    def handle_http(err):
        code = (err.name or "error").upper().replace(" ", "_")
        messages = {
            401: "Please log in to continue.",
            403: "Access denied.",
            404: "The requested resource was not found.",
            405: "This method is not allowed for this URL.",
            413: "The uploaded file is too large (max 2 MB).",
            415: "Send the request body as JSON with Content-Type: application/json.",
        }
        message = messages.get(err.code, err.description)
        return _render(err.code, code, message)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # Never leak tracebacks or internal messages to the client.
        db.session.rollback()
        app.logger.exception("Unhandled error")
        return _render(500, "INTERNAL_ERROR", "An unexpected error occurred.")
