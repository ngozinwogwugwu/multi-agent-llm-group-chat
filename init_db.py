from app import create_app, db
from app.models import User, SlackBot, Message, Document
import psycopg2
from sqlalchemy import inspect, text
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def init_database():
    app = create_app()
    with app.app_context():
        # Create pgvector extension
        print("Creating pgvector extension...")
        try:
            db.session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            db.session.commit()
        except Exception as e:
            print(f"Error creating extension: {e}")
            db.session.rollback()

        # Create tables
        print("Creating database tables...")
        db.create_all()

        # Check if client_msg_id column exists in Message table
        inspector = inspect(db.engine)
        columns = [col["name"] for col in inspector.get_columns("message")]

        # If client_msg_id doesn't exist, add it
        if "client_msg_id" not in columns:
            print("Adding client_msg_id column to Message table...")
            try:
                db.session.execute(
                    text("ALTER TABLE message ADD COLUMN client_msg_id VARCHAR(100)")
                )
                db.session.commit()
                print("Column added successfully")
            except Exception as e:
                print(f"Error adding column: {e}")
                db.session.rollback()

        # Add sample data if tables are empty
        if User.query.count() == 0:
            print("Adding sample data...")
            # Add your sample data here

        print("Database initialization complete!")


if __name__ == "__main__":
    init_database()
