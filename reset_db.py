# reset_db.py
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

engine = create_engine(os.getenv("NEON_DATABASE_URL"))

def reset_tables():
    print("Dropping old conflicting tables...")
    with engine.connect() as connection:
        # We must drop all tables we have ever created to avoid conflicts
        connection.execute(text("DROP TABLE IF EXISTS assessments CASCADE;"))
        connection.execute(text("DROP TABLE IF EXISTS candidates CASCADE;")) # The MVP table
        connection.execute(text("DROP TABLE IF EXISTS users CASCADE;"))      # The new Enterprise table
        connection.commit()
    print("✅ Tables dropped successfully! You have a clean slate.")

if __name__ == "__main__":
    reset_tables()