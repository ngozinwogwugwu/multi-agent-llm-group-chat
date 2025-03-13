from app import db, create_app
from app.models import Message, User, SlackBot


def init_database():
    print("Creating database tables...")
    app = create_app()
    with app.app_context():
        # Create the vector extension first
        db.session.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        db.session.commit()

        # Then create tables
        db.create_all()
    print("Database tables created successfully!")


if __name__ == "__main__":
    init_database()
