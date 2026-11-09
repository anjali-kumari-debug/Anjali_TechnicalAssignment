"""Application factory."""
from flask import Flask, Request
from werkzeug.exceptions import BadRequest

from .config import Config
from .extensions import csrf, db, login_manager


class AppRequest(Request):
    def on_json_loading_failed(self, e):
        if e is None:  # wrong Content-Type: Werkzeug raises 415 Unsupported Media Type
            return super().on_json_loading_failed(e)
        raise BadRequest("The request body is not valid JSON.")


def create_app(config_class=Config):
    app = Flask(__name__)
    app.request_class = AppRequest
    app.config.from_object(config_class)
    if not app.config.get("SQLALCHEMY_DATABASE_URI"):
        raise RuntimeError("DATABASE_URL is not set. Copy .env.example to .env and fill it in.")
    if not app.config.get("SECRET_KEY"):
        raise RuntimeError("SECRET_KEY is not set. Copy .env.example to .env and fill it in.")

    db.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please log in to continue."
    # For /api/* return 401 JSON instead of redirecting fetch() to the HTML login page.
    login_manager.blueprint_login_views = {"api": None}

    from .models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    from .errors import register_error_handlers
    from .routes.api import api_bp
    from .routes.auth import auth_bp
    from .routes.web import web_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(web_bp)
    app.register_blueprint(api_bp, url_prefix="/api")
    register_error_handlers(app)

    from .formatting import format_inr

    app.add_template_filter(format_inr, "inr")

    from .cli import register_cli

    register_cli(app)
    return app
