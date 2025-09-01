# Task Table Helper

A comprehensive utility for managing and monitoring tasks in the SeedCore system.

## Features

- **Task Listing**: List tasks with various filters (status, type, domain)
- **Task Details**: Show detailed information for specific tasks
- **Task Statistics**: Display comprehensive task statistics and health metrics
- **Task ID Printing**: Enhanced task ID logging and display
- **Database Integration**: Direct PostgreSQL database access
- **Async Support**: Full async/await support for high performance

## Quick Start

### Command Line Usage

```bash
# List all tasks
python scripts/task_table_helper.py list

# List running tasks
python scripts/task_table_helper.py list --status running

# List tasks by type
python scripts/task_table_helper.py list --type graph_embed

# Show detailed task information
python scripts/task_table_helper.py show <task_id>

# Show task statistics
python scripts/task_table_helper.py stats

# Show statistics as JSON
python scripts/task_table_helper.py stats --json
```

### Programmatic Usage

```python
from scripts.task_table_helper import TaskTableHelper

async def example():
    async with TaskTableHelper() as helper:
        # List tasks
        tasks = await helper.list_tasks(status="running")
        
        # Get specific task
        task = await helper.get_task_by_id("task-uuid-here")
        
        # Print task details
        helper.print_task_details(task)
        
        # Get statistics
        stats = await helper.get_task_statistics()
        helper.print_statistics(stats)
```

## Task Table Schema

The tasks table contains the following columns:

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key, unique task identifier |
| `status` | ENUM | Task status: created, queued, running, completed, failed, cancelled, retry |
| `type` | TEXT | Task type (e.g., graph_embed, graph_rag_query) |
| `description` | TEXT | Human-readable task description |
| `domain` | TEXT | Domain context for the task |
| `drift_score` | DOUBLE | Drift score for the task |
| `attempts` | INTEGER | Number of execution attempts |
| `locked_by` | TEXT | Dispatcher that has locked the task |
| `locked_at` | TIMESTAMP | When the task was locked |
| `run_after` | TIMESTAMP | When the task should run (for retries) |
| `params` | JSONB | Task parameters |
| `result` | JSONB | Task execution result |
| `error` | TEXT | Error message if task failed |
| `created_at` | TIMESTAMP | When the task was created |
| `updated_at` | TIMESTAMP | When the task was last updated |

## Task Status Lifecycle

```
created → queued → running → completed
    ↓         ↓        ↓
  failed ← retry ← failed
    ↓
cancelled
```

## Enhanced Logging

The queue dispatcher now includes enhanced task ID logging:

- **Task Processing**: Logs task ID when processing starts
- **Task Execution**: Logs task ID when sending to OrganismManager
- **Task Completion**: Logs task ID with completion status
- **Task Failure**: Logs task ID with failure details and attempt count
- **Task Retry**: Logs task ID with retry information and delay

Example log output:
```
[QueueDispatcher] 🚀 Processing task 123e4567-e89b-12d3-a456-426614174000 (type=graph_embed, domain=user_123, attempts=0)
[QueueDispatcher] 📋 Task ID: 123e4567-e89b-12d3-a456-426614174000 | Type: graph_embed | Domain: user_123 | Attempts: 0
[QueueDispatcher] 📤 Sending task 123e4567-e89b-12d3-a456-426614174000 to OrganismManager for execution
[QueueDispatcher] 🎯 Task ID: 123e4567-e89b-12d3-a456-426614174000 | Executing task type: graph_embed
[QueueDispatcher] ✅ Task 123e4567-e89b-12d3-a456-426614174000 completed successfully
[QueueDispatcher] 🎉 Task ID: 123e4567-e89b-12d3-a456-426614174000 | Status: COMPLETED | Type: graph_embed
```

## Configuration

The helper uses the following environment variables:

- `PG_DSN` or `SEEDCORE_PG_DSN`: PostgreSQL connection string
- Default: `postgresql://postgres:postgres@postgresql:5432/seedcore`

## Dependencies

- `asyncpg`: Async PostgreSQL driver
- `psycopg2-binary`: PostgreSQL adapter for Python
- `json`: JSON handling (built-in)
- `datetime`: Date/time handling (built-in)

## Examples

### List Recent Tasks
```bash
python scripts/task_table_helper.py list --limit 20
```

### Monitor Running Tasks
```bash
python scripts/task_table_helper.py list --status running
```

### Check Failed Tasks
```bash
python scripts/task_table_helper.py list --status failed --limit 10
```

### Get Task Statistics
```bash
python scripts/task_table_helper.py stats
```

### Show Specific Task
```bash
python scripts/task_table_helper.py show 123e4567-e89b-12d3-a456-426614174000
```

## Demo

Run the demo script to see all features in action:

```bash
python scripts/demo_task_helper.py
```

## Integration with Queue Dispatcher

The task table helper works seamlessly with the enhanced queue dispatcher that now includes:

- Comprehensive task ID logging
- Status tracking with emojis
- Attempt counting and retry logic
- Error handling with detailed logging
- Performance metrics and monitoring

This provides a complete task management and monitoring solution for the SeedCore system.
