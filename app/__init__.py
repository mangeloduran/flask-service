from flask import Flask

from app.config import Config
from app.routes import health, api
from app.routes.service import lotto_number_gen


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    app.register_blueprint(health.bp)
    app.register_blueprint(api.bp)
    app.register_blueprint(lotto_number_gen.bp) 
    
    return app
