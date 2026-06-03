import json
from datetime import datetime
from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy

from sqlalchemy.ext.hybrid import hybrid_property

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    mood_entries = db.relationship("MoodEntry", backref="user", lazy=True)
    assessments = db.relationship("Assessment", backref="user", lazy=True)

    def get_id(self):
        return str(self.id)

class MoodEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    mood_score = db.Column(db.Integer, nullable=False)
    stress_level = db.Column(db.Integer, nullable=False)
    note = db.Column(db.Text, nullable=True)
    date = db.Column(db.Date, nullable=False)

class Assessment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    score = db.Column(db.Integer, nullable=False)
    severity = db.Column(db.String(50), nullable=False)
    answers_json = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @hybrid_property
    def answers(self):
        try:
            return json.loads(self.answers_json)
        except Exception:
            return []

class Recommendation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    score_range_min = db.Column(db.Integer, nullable=False)
    score_range_max = db.Column(db.Integer, nullable=False)
    tips = db.Column(db.Text, nullable=False)

    @hybrid_property
    def tips_list(self):
        try:
            return json.loads(self.tips)
        except Exception:
            return []

class BreathingSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    technique = db.Column(db.String(50), nullable=False)
    duration_minutes = db.Column(db.Integer, nullable=False)
    date = db.Column(db.Date, nullable=False)
