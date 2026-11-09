"""Application configuration, read from environment variables (.env in development)."""
import os

from dotenv import load_dotenv

load_dotenv()  # read .env (if present) before the classes below read os.environ


def _engine_options():
    # Fail fast instead of waiting 50 s when a row lock is held (see README, "Concurrency").
    return {
        "pool_pre_ping": True,
        "connect_args": {
            "init_command": "SET SESSION innodb_lock_wait_timeout = 5, SESSION lock_wait_timeout = 5",
        },
    }


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL")
    SQLALCHEMY_ENGINE_OPTIONS = _engine_options()
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"

    MAX_CONTENT_LENGTH = 2 * 1024 * 1024  # 2 MB upload limit (CSV import)
    WTF_CSRF_TIME_LIMIT = None  # token valid for the whole session

    PASSWORD_HASH_METHOD = "scrypt:131072:8:1"  # OWASP-recommended scrypt cost
    API_MAX_PER_PAGE = 100


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret-key"
    SQLALCHEMY_DATABASE_URI = os.environ.get("TEST_DATABASE_URL")
    WTF_CSRF_ENABLED = False
    # Cheap hashing keeps the test suite fast; production uses the strong setting above.
    PASSWORD_HASH_METHOD = "pbkdf2:sha256:1000"
