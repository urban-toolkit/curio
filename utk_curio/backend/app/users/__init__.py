from flask import Blueprint


bp = Blueprint('users', __name__)

from utk_curio.backend.app.users import models