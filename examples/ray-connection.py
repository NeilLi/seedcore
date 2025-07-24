"""
Example: Flexible Ray connection for SeedCore.
Demonstrates how to connect to local or remote Ray clusters using environment variables.
"""

import os
import sys
sys.path.append('../src')

from seedcore.utils.ray_utils import init_ray, test_ray_connection, get_ray_cluster_info
from seedcore.config.ray_config import configure_ray_remote, configure_ray_local


def example_local_ray():
    """Example: Connect to local Ray cluster."""
    print("=== Local Ray Connection Example ===")
    
    # Method 1: Use environment variables
    # Set RAY_ADDRESS="" or don't set it for local connection
    os.environ.pop('RAY_ADDRESS', None)  # Ensure no remote address
    os.environ.pop('RAY_HOST', None)     # Ensure no remote host
    
    success = init_ray()
    if success:
        print("✅ Local Ray connection successful")
        info = get_ray_cluster_info()
        print(f"Cluster info: {info}")
    else:
        print("❌ Local Ray connection failed")


def example_remote_ray():
    """Example: Connect to remote Ray cluster."""
    print("\n=== Remote Ray Connection Example ===")
    
    # Method 1: Use environment variables (recommended)
    # export RAY_ADDRESS="ray://YOUR_REMOTE_HOST:10001"
    # export RAY_HOST="YOUR_REMOTE_HOST"
    # export RAY_PORT="10001"
    
    # Method 2: Configure programmatically (for testing)
    remote_host = os.getenv('RAY_HOST', 'YOUR_REMOTE_HOST')
    remote_port = int(os.getenv('RAY_PORT', '10001'))
    
    if remote_host != 'YOUR_REMOTE_HOST':
        configure_ray_remote(
            host=remote_host,
            port=remote_port,
            password=os.getenv('RAY_PASSWORD')  # Add password if needed
        )
        
        success = init_ray()
        if success:
            print("✅ Remote Ray connection successful")
            info = get_ray_cluster_info()
            print(f"Cluster info: {info}")
        else:
            print("❌ Remote Ray connection failed")
    else:
        print("⚠️  Set RAY_HOST environment variable to test remote connection")


def example_environment_based():
    """Example: Use environment variables for configuration."""
    print("\n=== Environment-based Configuration Example ===")
    
    # Set environment variables (in practice, these would be in your .env file or system)
    # Example values - replace with your actual remote host
    example_host = os.getenv('RAY_HOST', 'YOUR_REMOTE_HOST')
    example_port = os.getenv('RAY_PORT', '10001')
    example_namespace = os.getenv('RAY_NAMESPACE', 'seedcore-dev')
    
    if example_host != 'YOUR_REMOTE_HOST':
        os.environ['RAY_HOST'] = example_host
        os.environ['RAY_PORT'] = example_port
        os.environ['RAY_NAMESPACE'] = example_namespace
        
        success = init_ray()
        if success:
            print("✅ Environment-based Ray connection successful")
            test_result = test_ray_connection()
            print(f"Connection test: {'✅ Passed' if test_result else '❌ Failed'}")
        else:
            print("❌ Environment-based Ray connection failed")
    else:
        print("⚠️  Set RAY_HOST environment variable to test environment-based connection")


def example_flexible_connection():
    """Example: Flexible connection based on environment."""
    print("\n=== Flexible Connection Example ===")
    
    # Check if we should use remote or local
    ray_host = os.getenv('RAY_HOST')
    ray_address = os.getenv('RAY_ADDRESS')
    
    if ray_host and ray_host != 'YOUR_REMOTE_HOST' or ray_address:
        print(f"Using remote Ray: {ray_host or ray_address}")
        success = init_ray()
    else:
        print("Using local Ray (no remote configuration found)")
        success = init_ray()
    
    if success:
        print("✅ Ray connection successful")
        info = get_ray_cluster_info()
        print(f"Status: {info.get('status', 'unknown')}")
    else:
        print("❌ Ray connection failed")


def show_environment_setup():
    """Show how to set up environment variables."""
    print("\n=== Environment Setup Guide ===")
    print("To use remote Ray, set these environment variables:")
    print()
    print("# For remote Ray cluster")
    print("export RAY_HOST=your-remote-vm-ip")
    print("export RAY_PORT=10001")
    print("export RAY_NAMESPACE=seedcore")
    print()
    print("# Or use full address")
    print("export RAY_ADDRESS=ray://your-remote-vm-ip:10001")
    print()
    print("# Optional settings")
    print("export RAY_PASSWORD=your-password  # if needed")
    print("export RAY_IGNORE_REINIT_ERROR=true")
    print("export RAY_CONNECTION_TIMEOUT=30")
    print()
    print("# For local Ray, don't set RAY_HOST or RAY_ADDRESS")


if __name__ == "__main__":
    print("SeedCore Ray Connection Examples")
    print("=" * 40)
    
    # Show environment setup guide
    show_environment_setup()
    
    # Run examples
    example_local_ray()
    example_remote_ray()
    example_environment_based()
    example_flexible_connection()
    
    print("\n" + "=" * 40)
    print("Examples completed!")
    print("\n💡 Tip: Set environment variables to test remote connections")

