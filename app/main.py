from flask import Flask
from app.config import Config


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder="../templates",
        static_folder="../static",
    )
    app.config.from_object(Config)

    from app.review.routes import bp
    app.register_blueprint(bp)

    return app
