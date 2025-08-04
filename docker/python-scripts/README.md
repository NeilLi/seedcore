# Python Scripts

This directory contains all Python scripts for testing, demos, and verification of the SeedCore system.

## Scripts Overview

### Test Scripts
- **`test_*.py`** - Integration and unit tests
  - `test_ray_basic.py` - Basic Ray functionality tests
  - `test_serve_simple.py` - Ray Serve simple tests
  - `test_xgboost_docker.py` - XGBoost Docker integration tests
  - `test_xgboost_integration_simple.py` - Simple XGBoost integration tests
  - `test_xgboost_minimal.py` - Minimal XGBoost tests

### Demo Scripts
- **`*_demo.py`** - Demonstration scripts
  - `xgboost_coa_integration_demo.py` - XGBoost COA integration demo
  - `xgboost_docker_demo.py` - XGBoost Docker demo

### Verification Scripts
- **`verify_*.py`** - Verification and validation scripts
  - `verify_xgboost_service.py` - XGBoost service verification

### Initialization Scripts
- **`init_*.py`** - Service initialization scripts
  - `init_xgboost_service.py` - XGBoost service initialization

## Usage

### Running Scripts Inside Docker Container
```bash
# Navigate to the python-scripts directory inside the container
docker exec -it seedcore-ray-head cd /app/docker/python-scripts

# Run a test script
python test_xgboost_integration_simple.py

# Run a demo script
python xgboost_docker_demo.py
```

### Running Scripts from Host
```bash
# From the docker directory
cd python-scripts

# Run a test script (requires Docker container to be running)
python test_xgboost_integration_simple.py
```

## Dependencies

These scripts require:
- Python 3.8+
- Ray framework
- XGBoost
- NumPy, Pandas
- Requests library

All dependencies are available in the SeedCore Docker containers.

## Notes

- Scripts use absolute paths for imports (`/app`, `/app/src`)
- Scripts are designed to run inside the Docker container environment
- Some scripts may require the SeedCore cluster to be running
- Check individual script headers for specific usage instructions 