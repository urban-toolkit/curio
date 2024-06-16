from flask import request, jsonify, g
from functools import wraps
from models import UserSession, User
from extensions import db

def require_auth(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({'error': 'Authorization token is missing'}), 401
        
        session = UserSession.query.filter_by(token=token, active=True).first()
        if not session:
            return jsonify({'error': 'Invalid or expired token'}), 403
        
        user = User.query.filter_by(id=session.user_id).first()
        if not user:
            return jsonify({'error': 'User not found'}), 404

        g.user = user  # Attach user to global g object
        return f(*args, **kwargs)
    return decorated_function