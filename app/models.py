from app import db
from pgvector.sqlalchemy import Vector
from datetime import datetime


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    slack_user_id = db.Column(db.String(50), unique=True, nullable=False)
    username = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    messages = db.relationship(
        "Message", backref="user", lazy=True, foreign_keys="Message.user_id"
    )

    def __repr__(self):
        return f"<User {self.username}>"


class SlackBot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bot_id = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    messages = db.relationship(
        "Message", backref="bot", lazy=True, foreign_keys="Message.bot_id"
    )
    documents = db.relationship("Document", backref="bot", lazy=True)

    def __repr__(self):
        return f"<SlackBot {self.name}>"


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    channel = db.Column(db.String(100), nullable=False)
    text = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Vector field for future use with embeddings
    embedding = db.Column(Vector(1536))

    # Link to either a user or a bot (one of these will be NULL)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    bot_id = db.Column(db.Integer, db.ForeignKey("slack_bot.id"), nullable=True)

    # Flag to quickly identify message source
    is_bot = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f"<Message {self.id}: {self.text[:20]}...>"


class Document(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    # Vector field for embeddings
    embedding = db.Column(Vector(1536))

    # Link to bot owner
    bot_id = db.Column(db.Integer, db.ForeignKey("slack_bot.id"), nullable=False)

    def __repr__(self):
        return f"<Document {self.title}>"
