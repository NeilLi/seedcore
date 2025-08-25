#!/usr/bin/env python3
"""
Simple database initialization script for SeedCore.

This script creates the necessary database tables without heavy dependencies.
"""

import sys
import os
from sqlalchemy import create_engine, text

def get_sync_pg_engine():
    dsn = os.getenv("PG_DSN")
    if not dsn:
        raise RuntimeError("Missing PG_DSN environment variable")
    return create_engine(dsn, echo=False, future=True)

def init_database():
    """Initialize the database with required tables."""
    try:
        print("🚀 Connecting to database...")
        engine = get_sync_pg_engine()
        
        print("🚀 Creating database tables...")
        
        # Import models here to avoid circular imports
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
        from seedcore.models.task import Base as TaskBase
        from seedcore.models.fact import Base as FactBase
        
        # Create tables using synchronous methods
        TaskBase.metadata.create_all(engine)
        FactBase.metadata.create_all(engine)
        
        print("✅ Database tables created successfully!")
        print("📋 Tables created:")
        for table in TaskBase.metadata.tables.values():
            print(f"   - {table.name}")
        for table in FactBase.metadata.tables.values():
            print(f"   - {table.name}")
        
        # Test the connection
        print("🔍 Testing database connection...")
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version()"))
            version = result.scalar()
            print(f"✅ Connected to: {version}")
            
    except Exception as e:
        print(f"❌ Database initialization failed: {e}")
        sys.exit(1)
    finally:
        if 'engine' in locals():
            engine.dispose()

def main():
    """Main function to run database initialization."""
    print("🚀 SeedCore Simple Database Initialization")
    print("=" * 50)
    
    # Initialize the database
    init_database()
    
    print("\n🎉 Database initialization completed successfully!")
    print("You can now run the tests.")

if __name__ == "__main__":
    main()
