from flask import Blueprint

bp = Blueprint('api', __name__)

from utk_curio.backend.app.api import routes