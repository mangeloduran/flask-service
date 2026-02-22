from flask import Flask

from app.config import Config
from app.routes import health, api


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    app.register_blueprint(health.bp)
    app.register_blueprint(api.bp)

    return app
