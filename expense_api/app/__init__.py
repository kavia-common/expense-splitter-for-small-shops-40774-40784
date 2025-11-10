"""Flask application factory and API registration.

This module creates the Flask app, enables CORS, configures OpenAPI/Swagger UI,
initializes database teardown hooks, and registers all blueprints:
- health
- members
- expenses
- balances

The Api instance (flask-smorest) is exposed as `api` for OpenAPI generation.
"""

from flask import Flask
from flask_cors import CORS
from flask_smorest import Api

from .db import init_app as init_db
from .routes.health import blp as health_blp
from .routes.members import blp as members_blp  # register members blueprint
from .routes.expenses import blp as expenses_blp  # register expenses blueprint
from .routes.balances import blp as balances_blp  # register balances blueprint


# PUBLIC_INTERFACE
app = Flask(__name__)
app.url_map.strict_slashes = False

# Keep CORS enabled for all routes; origins can be tightened via env if needed
CORS(app, resources={r"/*": {"origins": "*"}})

# OpenAPI / Swagger UI configuration
app.config["API_TITLE"] = "My Flask API"
app.config["API_VERSION"] = "v1"
app.config["OPENAPI_VERSION"] = "3.0.3"
app.config["OPENAPI_URL_PREFIX"] = "/docs"
app.config["OPENAPI_SWAGGER_UI_PATH"] = ""
app.config["OPENAPI_SWAGGER_UI_URL"] = "https://cdn.jsdelivr.net/npm/swagger-ui-dist/"

# Initialize API and DB teardown integration
api = Api(app)
init_db(app)

# Register blueprints
api.register_blueprint(health_blp)
api.register_blueprint(members_blp)
api.register_blueprint(expenses_blp)
api.register_blueprint(balances_blp)
