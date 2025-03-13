from app import create_app, db
from app.models import Message
from sqlalchemy import text

app = create_app()


def init_database():
    with app.app_context():
        # Create the pgvector extension first
        print("Creating pgvector extension...")
        db.session.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        db.session.commit()

        print("Creating database tables...")
        db.create_all()

        # Check if there are any records
        if Message.query.count() == 0:
            print("Adding sample message...")
            sample = Message(
                channel="#all-the-circuit-board",
                text="This is a sample message created during initialization.",
            )
            db.session.add(sample)
            db.session.commit()
            print("Sample data added.")

        print("Database initialization complete!")


if __name__ == "__main__":
    init_database()
