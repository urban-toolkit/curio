from flask import Blueprint


bp = Blueprint('users', __name__)

from backend.app.users import models