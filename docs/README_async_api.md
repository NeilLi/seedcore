# Asynchronous XGBoost Tuning API

This document describes the new asynchronous API for XGBoost hyperparameter tuning in SeedCore.

## Overview

The asynchronous API breaks the long-running tuning process into two separate, fast requests:

1. **Submit Job**: Submit a tuning configuration and get a job ID immediately
2. **Check Status**: Poll the job status until completion

This approach makes the service more robust and provides better user experience.

## API Endpoints

### 1. Submit Tuning Job

**Endpoint**: `POST /ml_serve/xgboost/tune/submit`

**Request Body**:
```json
{
    "space_type": "conservative",
    "config_type": "conservative",
    "experiment_name": "my_tuning_experiment",
    "custom_search_space": null,
    "custom_tune_config": null
}
```

**Response**:
```json
{
    "status": "submitted",
    "job_id": "tune-a1b2c3d4",
    "message": "Tuning job submitted successfully. Use the job_id to check status."
}
```

### 2. Check Job Status

**Endpoint**: `GET /ml_serve/xgboost/tune/status/{job_id}`

**Response**:
```json
{
    "status": "RUNNING",
    "result": null,
    "progress": "Starting tuning sweep...",
    "submitted_at": "2024-01-15 10:30:45"
}
```

**Status Values**:
- `PENDING`: Job submitted, waiting to start
- `RUNNING`: Job is currently executing
- `COMPLETED`: Job finished successfully
- `FAILED`: Job failed with an error

### 3. List All Jobs

**Endpoint**: `GET /ml_serve/xgboost/tune/jobs`

**Response**:
```json
{
    "total_jobs": 2,
    "jobs": [
        {
            "job_id": "tune-a1b2c3d4",
            "status": "completed",
            "progress": "Tuning sweep completed successfully",
            "submitted_at": "2024-01-15 10:30:45"
        },
        {
            "job_id": "tune-e5f6g7h8",
            "status": "running",
            "progress": "Starting tuning sweep...",
            "submitted_at": "2024-01-15 10:35:22"
        }
    ]
}
```

## Client Usage Example

```python
import requests
import time

def run_async_tuning():
    base_url = "http://localhost:8000"
    ml_service_url = f"{base_url}/ml_serve"
    
    # Step 1: Submit the job
    payload = {
        "space_type": "conservative",
        "config_type": "conservative",
        "experiment_name": "my_experiment"
    }
    
    submit_response = requests.post(f"{ml_service_url}/xgboost/tune/submit", json=payload)
    submit_response.raise_for_status()
    job_id = submit_response.json()["job_id"]
    
    print(f"Job submitted with ID: {job_id}")
    
    # Step 2: Poll for completion
    while True:
        status_response = requests.get(f"{ml_service_url}/xgboost/tune/status/{job_id}")
        status_response.raise_for_status()
        status = status_response.json()
        
        print(f"Status: {status['status']} - {status['progress']}")
        
        if status['status'] == 'completed':
            result = status['result']
            print(f"Tuning completed! Best AUC: {result['best_trial']['auc']:.4f}")
            break
        elif status['status'] == 'failed':
            print(f"Tuning failed: {status['result']['error']}")
            break
        
        time.sleep(15)  # Poll every 15 seconds
```

## Benefits

1. **Immediate Response**: Users get a job ID instantly instead of waiting for completion
2. **Progress Tracking**: Real-time status updates and progress information
3. **Better UX**: Users can submit multiple jobs and track them independently
4. **Robustness**: Network timeouts don't affect long-running jobs
5. **Scalability**: Multiple tuning jobs can run concurrently

## Implementation Details

- **Job Storage**: In-memory dictionary (for production, use Redis or database)
- **Background Execution**: Uses `asyncio.create_task()` for non-blocking job execution
- **Status Updates**: Real-time status updates as jobs progress
- **Error Handling**: Comprehensive error handling and status reporting

## Testing

Use the provided test scripts:

1. **`test_async_api.py`**: Quick test of async endpoints
2. **`xgboost_demo.py`**: Full demo with async tuning

## Migration from Synchronous API

The original synchronous endpoint `/xgboost/tune` is still available for backward compatibility. New applications should use the async endpoints for better user experience.

## Production Considerations

1. **Persistent Storage**: Replace in-memory storage with Redis or database
2. **Job Cleanup**: Implement job cleanup for completed/failed jobs
3. **Authentication**: Add authentication and authorization
4. **Rate Limiting**: Implement rate limiting for job submission
5. **Monitoring**: Add metrics and monitoring for job execution
