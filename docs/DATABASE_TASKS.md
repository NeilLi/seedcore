# Database-Backed Task Management System

This document describes the refactored task management system that has been upgraded from a file-based approach to a scalable, database-backed service.

## Overview

The task management system has been completely refactored to use PostgreSQL as the backend storage instead of JSON files. This provides:

- **Scalability**: Handle millions of tasks without performance degradation
- **Data Integrity**: Transactional database ensures consistent task states
- **Performance**: Database lookups are significantly faster than parsing large JSON files
- **Reliability**: Concurrent access is handled safely by the database

## Architecture

### Components

1. **Task Model** (`src/seedcore/models/task.py`)
   - SQLAlchemy ORM model for the `Task` entity
   - Maps task attributes to database columns
   - Includes status enum and utility methods

2. **Fact Model** (`src/seedcore/models/fact.py`)
   - SQLAlchemy ORM model for the `Fact` entity
   - Stores text, tags, and metadata with timestamps
   - Supports efficient searching and filtering

3. **Refactored Task Router** (`src/seedcore/api/routers/tasks_router.py`)
   - All file I/O operations replaced with database operations
   - Uses FastAPI dependency injection for database sessions
   - Background worker creates dedicated database sessions for each task

4. **Refactored Control Router** (`src/seedcore/api/routers/control_router.py`)
   - Replaced file-based fact storage with database operations
   - Advanced search capabilities using SQL features
   - Efficient tag filtering and metadata search

5. **Main Application** (`src/seedcore/main.py`)
   - Demonstrates lifespan management for database initialization
   - Creates both tasks and facts tables on startup
   - Starts background task worker on application startup
   - Graceful shutdown handling

## Database Schema

### Tasks Table

```sql
CREATE TABLE tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type VARCHAR NOT NULL,
    description VARCHAR,
    params JSONB DEFAULT '{}',
    domain VARCHAR,
    drift_score FLOAT DEFAULT 0.0,
    status VARCHAR NOT NULL DEFAULT 'created',
    result JSONB,
    error VARCHAR,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### Facts Table

```sql
CREATE TABLE facts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    text VARCHAR NOT NULL,
    tags TEXT[] DEFAULT '{}',
    meta_data JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### Task Status Enum

- `CREATED`: Task has been created but not queued
- `QUEUED`: Task is in the execution queue
- `RUNNING`: Task is currently being executed
- `COMPLETED`: Task completed successfully
- `FAILED`: Task failed during execution
- `CANCELLED`: Task was cancelled

## Setup Instructions

### 1. Database Initialization

Run the database initialization script:

```bash
python scripts/init_database.py
```

This will:
- Check database connectivity
- Create the `tasks` table if it doesn't exist
- Verify the setup

### 2. Environment Variables

Ensure these environment variables are set:

```bash
# PostgreSQL Configuration
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=seedcore
POSTGRES_USER=seedcore
POSTGRES_PASSWORD=your_password

# Or use a single DSN
PG_DSN=postgresql://user:password@host:port/database
```

### 3. Running the Application

#### Option A: Using the Main Application

```bash
python -m src.seedcore.main
```

#### Option B: Using Uvicorn Directly

```bash
uvicorn src.seedcore.main:app --host 0.0.0.0 --port 8000 --reload
```

#### Option C: Integration with Existing Entrypoints

Add the lifespan management to your existing entrypoint:

```python
from contextlib import asynccontextmanager
from seedcore.database import get_async_pg_engine
from seedcore.models.task import Base
from seedcore.api.routers.tasks_router import _task_worker

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database
    engine = get_async_pg_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Start worker
    worker_task = asyncio.create_task(_task_worker(app.state))
    
    yield
    
    # Shutdown
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass

app = FastAPI(lifespan=lifespan)
```

## API Endpoints

### Task Management

#### Create Task

```http
POST /api/v1/tasks
Content-Type: application/json

{
    "type": "analysis_task",
    "params": {"input_file": "data.csv"},
    "description": "Analyze the input data",
    "domain": "data_science",
    "drift_score": 0.3,
    "run_immediately": true
}
```

#### List Tasks

```http
GET /api/v1/tasks
```

#### Get Task

```http
GET /api/v1/tasks/{task_id}
```

#### Run Task

```http
POST /api/v1/tasks/{task_id}/run
```

#### Cancel Task

```http
POST /api/v1/tasks/{task_id}/cancel
```

#### Task Status

```http
GET /api/v1/tasks/{task_id}/status
```

### Fact Management

#### Create Fact

```http
POST /api/v1/facts
Content-Type: application/json

{
    "text": "This is an important fact",
    "tags": ["important", "reference"],
    "meta_data": {"source": "user_input", "priority": "high"}
}
```

#### List Facts

```http
GET /api/v1/facts?q=important&tag=reference&limit=50&offset=0
```

#### Get Fact

```http
GET /api/v1/facts/{fact_id}
```

#### Update Fact

```http
PATCH /api/v1/facts/{fact_id}
Content-Type: application/json

{
    "text": "Updated fact text",
    "tags": ["updated", "reference"]
}
```

#### Delete Fact

```http
DELETE /api/v1/facts/{fact_id}
```

## Background Worker

The background worker (`_task_worker`) runs continuously and:

1. Consumes tasks from the queue
2. Creates dedicated database sessions for each task
3. Updates task status to `RUNNING`
4. Executes the task via the OrganismManager
5. Updates the task with results and final status
6. Handles errors gracefully

## Testing

Run the comprehensive test suite:

```bash
python test_database_tasks.py
```

This will test:
- Task model creation and serialization
- Database connectivity
- Database operations (CRUD)
- Task router integration

## Migration from File-Based System

### What Changed

1. **Storage**: `tasks.json` → PostgreSQL database
2. **State Management**: In-memory dict → Database queries
3. **Persistence**: Manual file writes → Automatic database commits
4. **Worker**: File-based state → Database-backed state

### Benefits

- **No more file corruption**: Database handles concurrent writes safely
- **Better performance**: Indexed queries instead of file parsing
- **Scalability**: Can handle millions of tasks
- **Monitoring**: Database provides built-in monitoring capabilities
- **Backup**: Standard database backup procedures apply

### Compatibility

The API endpoints maintain the same interface, so existing clients will continue to work without changes.

## Troubleshooting

### Common Issues

1. **Database Connection Failed**
   - Check environment variables
   - Verify PostgreSQL is running
   - Check network connectivity

2. **Table Creation Failed**
   - Ensure database user has CREATE permissions
   - Check PostgreSQL logs for errors

3. **Worker Not Starting**
   - Verify database is accessible
   - Check application logs for startup errors

### Debug Mode

Enable debug logging by setting:

```bash
export LOG_LEVEL=DEBUG
```

## Performance Considerations

- **Connection Pooling**: The system uses SQLAlchemy's connection pooling
- **Indexes**: Consider adding indexes on frequently queried fields
- **Batch Operations**: For bulk operations, consider using bulk insert/update methods
- **Monitoring**: Use database monitoring tools to track query performance

## Future Enhancements

- **Task Scheduling**: Add cron-like scheduling capabilities
- **Task Dependencies**: Support for task workflows and dependencies
- **Retry Logic**: Automatic retry with exponential backoff
- **Metrics**: Integration with monitoring systems
- **Audit Trail**: Track all task state changes
