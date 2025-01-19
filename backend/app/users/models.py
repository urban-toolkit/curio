from extensions import db
from uuid import uuid4

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    profile_image = db.Column(db.String(200), nullable=True)
    type = db.Column(db.String(100), nullable=True)
    provider = db.Column(db.String(50), nullable=True)
    provider_uid = db.Column(db.String(200), nullable=True)

    def __repr__(self):
        return '<User %r>' % self.email

class UserSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    token = db.Column(db.String(36), unique=True, default=lambda: str(uuid4()), nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)

    # Relationship to User
    user = db.relationship('User', backref=db.backref('sessions', lazy=True))

    def __repr__(self):
        return '<UserSession %r>' % self.token
