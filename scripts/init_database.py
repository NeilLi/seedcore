#!/usr/bin/env python3
"""
Database initialization script for SeedCore.

This script can be run independently to create the necessary database tables
for the refactored task management system.
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

def check_database_health():
    """Check if the database is healthy and accessible."""
    try:
        print("🔍 Checking database health...")
        
        # Simple health check using the engine
        engine = get_sync_pg_engine()
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            health_check = result.scalar()
            if health_check == 1:
                print("✅ Database is healthy and accessible")
                return True
            else:
                print("❌ Database health check failed")
                return False
                
    except Exception as e:
        print(f"❌ Health check failed: {e}")
        return False
    finally:
        if 'engine' in locals():
            engine.dispose()

def main():
    """Main function to run database initialization."""
    print("🚀 SeedCore Database Initialization")
    print("=" * 50)
    
    # Check database health first
    if not check_database_health():
        print("❌ Cannot proceed with initialization due to database health issues")
        sys.exit(1)
    
    # Initialize the database
    init_database()
    
    print("\n🎉 Database initialization completed successfully!")
    print("You can now start the SeedCore application.")

if __name__ == "__main__":
    main()
