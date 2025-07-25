from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
import os

# Use environment variable or default for Postgres DSN
DATABASE_URL = os.getenv("PG_DSN", "postgresql+psycopg2://postgres:password@postgres:5432/postgres")

# MySQL configuration for Flashbulb Memory
MYSQL_DATABASE_URL = os.getenv("MYSQL_DATABASE_URL", "mysql+mysqlconnector://seedcore:password@seedcore-mysql:3306/seedcore")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# MySQL engine for Flashbulb Memory
mysql_engine = create_engine(MYSQL_DATABASE_URL)
MySQLSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=mysql_engine)

def get_db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_mysql_session():
    """Get MySQL database session for Flashbulb Memory"""
    db = MySQLSessionLocal()
    try:
        yield db
    finally:
        db.close() 