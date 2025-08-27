#!/usr/bin/env python3
import ray

# Connect to the cluster with the right namespace
ray.init(address="auto", namespace="seedcore-dev")

try:
    # Get the detached Janitor actor
    jan = ray.get_actor("seedcore_janitor", namespace="seedcore-dev")
    print("✅ Found actor:", jan)

    # List its methods and attributes
    print("\n📋 Available methods/attributes:")
    for m in dir(jan):
        print(" -", m)

except Exception as e:
    print("❌ Could not find Janitor actor:", e)

