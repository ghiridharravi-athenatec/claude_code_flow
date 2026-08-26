"""Flask application factory."""

from __future__ import annotations

import logging

from flask import Flask
from flask_cors import CORS

from config import Config
from routes.health import health_bp
from routes.rubrics import rubrics_bp
from routes.validate import validate_bp
from validation.rubric_loader import load_rubric

API_PREFIX = "/api/v1"


def create_app(config_class: type[Config] = Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_class)

    logging.basicConfig(level=app.config["LOG_LEVEL"])

    CORS(app, origins=[app.config["ALLOWED_ORIGIN"]])

    # Load once at startup; never re-read per request (CLAUDE.md rubric-file rule).
    load_rubric(app.config["RUBRIC_PATH"])

    app.register_blueprint(health_bp, url_prefix=API_PREFIX)
    app.register_blueprint(rubrics_bp, url_prefix=API_PREFIX)
    app.register_blueprint(validate_bp, url_prefix=API_PREFIX)

    return app


if __name__ == "__main__":
    create_app().run(debug=False)
