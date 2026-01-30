# HAL Bridge Testing Guide

This guide provides curl commands to verify HAL interaction with the Reachy simulation server.

## Prerequisites

- HAL bridge service running on `localhost:8001` (or configured port)
- Simulation server running as sidecar (or standalone on `localhost:50055`)
- `HAL_DRIVER_MODE=simulation` set in the deployment

## Test Endpoints

### 1. Check HAL Service Status

Verify the HAL service is running and connected to the simulation server:

```bash
curl http://localhost:8001/status
```

**Expected Response:**
```json
{
  "hardware_uuid": "...",
  "driver_mode": "simulation",
  "state": "connected",
  "proprioception": {
    "joint_positions": {},
    "ee_pose": {"x": 0.0, "y": 0.0, "z": 0.0, "yaw": 0.0, "pitch": 0.0, "roll": 0.0},
    "imu_data": {},
    "is_moving": false,
    "timestamp": 1234567890.0
  }
}
```

### 2. Get Current Robot State

Retrieve the current robot state (head pose, antennas, body yaw):

```bash
curl http://localhost:8001/state
```

**Expected Response:**
```json
{
  "head": {
    "x": 0.0,
    "y": 0.0,
    "z": 0.0,
    "yaw": 0.0,
    "pitch": 0.0,
    "roll": 0.0
  },
  "antennas": [0.0, 0.0],
  "body_yaw": 0.0
}
```

### 3. Send Motion Command (Head Movement)

Move the robot head:

```bash
curl -X POST http://localhost:8001/actuate \
  -H "Content-Type: application/json" \
  -d '{
    "pose_type": "head",
    "target": {
      "head": {
        "z": 20.0,
        "roll": 10.0
      }
    },
    "instant": false
  }'
```

**Expected Response:**
```json
{
  "status": "accepted",
  "robot_state": "moving"
}
```

### 4. Send Motion Command (Antennas)

Move the antennas:

```bash
curl -X POST http://localhost:8001/actuate \
  -H "Content-Type: application/json" \
  -d '{
    "pose_type": "antennas",
    "target": {
      "antennas": [0.785, -0.785]
    },
    "instant": false
  }'
```

**Expected Response:**
```json
{
  "status": "accepted",
  "robot_state": "moving"
}
```

### 5. Send Motion Command (Body Yaw)

Rotate the robot body:

```bash
curl -X POST http://localhost:8001/actuate \
  -H "Content-Type: application/json" \
  -d '{
    "pose_type": "body",
    "target": {
      "body_yaw": 0.524
    },
    "instant": false
  }'
```

**Expected Response:**
```json
{
  "status": "accepted",
  "robot_state": "moving"
}
```

### 6. Combined Motion Command

Move head, antennas, and body together:

```bash
curl -X POST http://localhost:8001/actuate \
  -H "Content-Type: application/json" \
  -d '{
    "pose_type": "head",
    "target": {
      "head": {
        "z": 15.0,
        "pitch": -10.0
      },
      "antennas": [0.5, 0.5],
      "body_yaw": 0.3
    },
    "instant": false
  }'
```

### 7. Instant Motion (High-Frequency)

Send instant motion command (for VLA token streaming):

```bash
curl -X POST http://localhost:8001/actuate \
  -H "Content-Type: application/json" \
  -d '{
    "pose_type": "head",
    "target": {
      "head": {
        "yaw": 0.2
      }
    },
    "instant": true
  }'
```

### 8. Verify State After Motion

After sending a motion command, verify the state changed:

```bash
# Send motion
curl -X POST http://localhost:8001/actuate \
  -H "Content-Type: application/json" \
  -d '{
    "pose_type": "head",
    "target": {
      "head": {"z": 20.0, "roll": 10.0}
    }
  }'

# Wait a moment, then check state
sleep 1
curl http://localhost:8001/state
```

## Testing Workflow

### Complete Test Sequence

```bash
#!/bin/bash

HAL_URL="http://localhost:8001"

echo "1. Checking HAL status..."
curl -s $HAL_URL/status | jq '.'

echo -e "\n2. Getting initial state..."
curl -s $HAL_URL/state | jq '.'

echo -e "\n3. Moving head..."
curl -s -X POST $HAL_URL/actuate \
  -H "Content-Type: application/json" \
  -d '{
    "pose_type": "head",
    "target": {"head": {"z": 20.0, "roll": 10.0}}
  }' | jq '.'

sleep 1

echo -e "\n4. Checking state after motion..."
curl -s $HAL_URL/state | jq '.'

echo -e "\n5. Moving antennas..."
curl -s -X POST $HAL_URL/actuate \
  -H "Content-Type: application/json" \
  -d '{
    "pose_type": "antennas",
    "target": {"antennas": [0.785, -0.785]}
  }' | jq '.'

sleep 1

echo -e "\n6. Final state check..."
curl -s $HAL_URL/state | jq '.'
```

## Troubleshooting

### Check if simulation server is running

If HAL status shows `state: "error"` or `state: "disconnected"`, verify the simulation server:

```bash
# Check if simulation server port is open
nc -z localhost 50055 && echo "Simulation server is running" || echo "Simulation server not accessible"

# Or use Python
python3 -c "import socket; s=socket.socket(); s.settimeout(1); result=s.connect_ex(('localhost', 50055)); s.close(); print('Connected' if result == 0 else 'Not connected')"
```

### Check HAL logs

```bash
# If running in Kubernetes
kubectl logs -n seedcore-dev deployment/seedcore-hal-bridge -c hal-driver

# Check simulation server logs
kubectl logs -n seedcore-dev deployment/seedcore-hal-bridge -c robot-sim-server
```

### Verify environment variables

```bash
# Check HAL driver mode
kubectl exec -n seedcore-dev deployment/seedcore-hal-bridge -c hal-driver -- env | grep HAL_DRIVER_MODE

# Check simulation address
kubectl exec -n seedcore-dev deployment/seedcore-hal-bridge -c hal-driver -- env | grep REACHY_SIM_ADDRESS
```

## Expected Behavior

1. **Status endpoint** should show `driver_mode: "simulation"` and `state: "connected"`
2. **State endpoint** should return current robot state from simulation server
3. **Actuate endpoint** should accept commands and return `status: "accepted"`
4. **State changes** should be reflected in subsequent `/state` calls

## Notes

- All angles are in **radians** (use `deg2rad` conversion if needed)
- Motion commands are **blocking** - the server waits for motion duration
- Simulation server runs on `localhost:50055` (same pod, hostNetwork)
- HAL service runs on port `8001` (configurable via NodePort 30001 in K8s)
