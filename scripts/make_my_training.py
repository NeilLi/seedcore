#!/usr/bin/env python3
"""
Data Generation Script for XGBoost Training

This script generates bespoke training datasets for XGBoost model training
as specified in Method 2 of the XGBoost integration instructions.

Usage:
    docker exec -it seedcore-ray-head python /app/scripts/make_my_training.py
"""

import os
import sys
import numpy as np
import pandas as pd
from sklearn.datasets import make_classification, make_regression
from datetime import datetime
import argparse


def generate_classification_dataset(
    n_samples: int = 50000,
    n_features: int = 32,
    n_informative: int = 24,
    n_redundant: int = 4,
    n_repeated: int = 0,
    n_classes: int = 2,
    random_state: int = 42,
    output_path: str = "/data/my_training.csv"
) -> str:
    """
    Generate a synthetic classification dataset.
    
    Args:
        n_samples: Number of samples
        n_features: Number of features
        n_informative: Number of informative features
        n_redundant: Number of redundant features
        n_repeated: Number of repeated features
        n_classes: Number of classes
        random_state: Random seed for reproducibility
        output_path: Output file path
        
    Returns:
        str: Path to the generated dataset
    """
    print(f"Generating classification dataset with {n_samples} samples and {n_features} features...")
    
    # Generate synthetic dataset
    X, y = make_classification(
        n_samples=n_samples,
        n_features=n_features,
        n_informative=n_informative,
        n_redundant=n_redundant,
        n_repeated=n_repeated,
        n_classes=n_classes,
        random_state=random_state
    )
    
    # Create feature names
    feature_names = [f"feature_{i}" for i in range(X.shape[1])]
    
    # Create DataFrame
    df = pd.DataFrame(X, columns=feature_names)
    df["target"] = y
    
    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    # Save to CSV
    df.to_csv(output_path, index=False)
    
    print(f"✅ Classification dataset saved to: {output_path}")
    print(f"   Samples: {len(df)}")
    print(f"   Features: {len(feature_names)}")
    print(f"   Classes: {df['target'].nunique()}")
    print(f"   Class distribution: {df['target'].value_counts().to_dict()}")
    
    return output_path


def generate_regression_dataset(
    n_samples: int = 50000,
    n_features: int = 32,
    n_informative: int = 24,
    noise: float = 0.1,
    random_state: int = 42,
    output_path: str = "/data/my_regression_training.csv"
) -> str:
    """
    Generate a synthetic regression dataset.
    
    Args:
        n_samples: Number of samples
        n_features: Number of features
        n_informative: Number of informative features
        noise: Noise level
        random_state: Random seed for reproducibility
        output_path: Output file path
        
    Returns:
        str: Path to the generated dataset
    """
    print(f"Generating regression dataset with {n_samples} samples and {n_features} features...")
    
    # Generate synthetic dataset
    X, y = make_regression(
        n_samples=n_samples,
        n_features=n_features,
        n_informative=n_informative,
        noise=noise,
        random_state=random_state
    )
    
    # Create feature names
    feature_names = [f"feature_{i}" for i in range(X.shape[1])]
    
    # Create DataFrame
    df = pd.DataFrame(X, columns=feature_names)
    df["target"] = y
    
    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    # Save to CSV
    df.to_csv(output_path, index=False)
    
    print(f"✅ Regression dataset saved to: {output_path}")
    print(f"   Samples: {len(df)}")
    print(f"   Features: {len(feature_names)}")
    print(f"   Target range: {df['target'].min():.3f} to {df['target'].max():.3f}")
    print(f"   Target mean: {df['target'].mean():.3f}")
    print(f"   Target std: {df['target'].std():.3f}")
    
    return output_path


def generate_utility_dataset(
    n_samples: int = 10000,
    output_path: str = "/data/utility_training.csv"
) -> str:
    """
    Generate a utility-focused dataset for risk prediction.
    
    This creates a dataset that mimics utility signals like:
    - Risk scores
    - Computational costs
    - Success probabilities
    
    Args:
        n_samples: Number of samples
        output_path: Output file path
        
    Returns:
        str: Path to the generated dataset
    """
    print(f"Generating utility dataset with {n_samples} samples...")
    
    # Generate base features
    np.random.seed(42)
    
    # Feature 1: Task complexity (0-1)
    task_complexity = np.random.beta(2, 5, n_samples)
    
    # Feature 2: Resource availability (0-1)
    resource_availability = np.random.beta(3, 2, n_samples)
    
    # Feature 3: Historical success rate (0-1)
    historical_success = np.random.beta(4, 2, n_samples)
    
    # Feature 4: Memory pressure (0-1)
    memory_pressure = np.random.beta(2, 3, n_samples)
    
    # Feature 5: Network latency (0-1)
    network_latency = np.random.beta(1, 4, n_samples)
    
    # Feature 6: Agent capability (0-1)
    agent_capability = np.random.beta(3, 1, n_samples)
    
    # Feature 7: Energy level (0-1)
    energy_level = np.random.beta(2, 2, n_samples)
    
    # Feature 8: Collaboration score (0-1)
    collaboration_score = np.random.beta(3, 2, n_samples)
    
    # Create target: Risk score (0-1, where 0 = low risk, 1 = high risk)
    # Higher complexity, memory pressure, network latency = higher risk
    # Higher resource availability, success rate, capability = lower risk
    risk_score = (
        0.3 * task_complexity +
        0.2 * memory_pressure +
        0.15 * network_latency +
        -0.2 * resource_availability +
        -0.1 * historical_success +
        -0.05 * agent_capability
    )
    
    # Add some noise
    risk_score += np.random.normal(0, 0.05, n_samples)
    
    # Clip to [0, 1]
    risk_score = np.clip(risk_score, 0, 1)
    
    # Create DataFrame
    df = pd.DataFrame({
        'task_complexity': task_complexity,
        'resource_availability': resource_availability,
        'historical_success': historical_success,
        'memory_pressure': memory_pressure,
        'network_latency': network_latency,
        'agent_capability': agent_capability,
        'energy_level': energy_level,
        'collaboration_score': collaboration_score,
        'target': risk_score
    })
    
    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    # Save to CSV
    df.to_csv(output_path, index=False)
    
    print(f"✅ Utility dataset saved to: {output_path}")
    print(f"   Samples: {len(df)}")
    print(f"   Features: {len(df.columns) - 1}")
    print(f"   Risk score range: {df['target'].min():.3f} to {df['target'].max():.3f}")
    print(f"   Risk score mean: {df['target'].mean():.3f}")
    print(f"   Risk score std: {df['target'].std():.3f}")
    
    return output_path


def main():
    """Main function to generate datasets."""
    parser = argparse.ArgumentParser(description="Generate training datasets for XGBoost")
    parser.add_argument("--type", choices=["classification", "regression", "utility"], 
                       default="classification", help="Dataset type")
    parser.add_argument("--samples", type=int, default=50000, help="Number of samples")
    parser.add_argument("--features", type=int, default=32, help="Number of features")
    parser.add_argument("--output", type=str, help="Output file path")
    parser.add_argument("--random-state", type=int, default=42, help="Random seed")
    
    args = parser.parse_args()
    
    # Set default output path based on type
    if not args.output:
        if args.type == "classification":
            args.output = "/data/my_training.csv"
        elif args.type == "regression":
            args.output = "/data/my_regression_training.csv"
        else:  # utility
            args.output = "/data/utility_training.csv"
    
    print(f"🎯 Generating {args.type} dataset...")
    print(f"   Samples: {args.samples}")
    print(f"   Features: {args.features}")
    print(f"   Output: {args.output}")
    print(f"   Random seed: {args.random_state}")
    print()
    
    try:
        if args.type == "classification":
            generate_classification_dataset(
                n_samples=args.samples,
                n_features=args.features,
                random_state=args.random_state,
                output_path=args.output
            )
        elif args.type == "regression":
            generate_regression_dataset(
                n_samples=args.samples,
                n_features=args.features,
                random_state=args.random_state,
                output_path=args.output
            )
        else:  # utility
            generate_utility_dataset(
                n_samples=args.samples,
                output_path=args.output
            )
        
        print(f"\n🎉 Dataset generation completed successfully!")
        print(f"   File: {args.output}")
        print(f"   Size: {os.path.getsize(args.output) / 1024 / 1024:.2f} MB")
        print(f"   Generated at: {datetime.now().isoformat()}")
        
        # Print next steps
        print(f"\n📋 Next steps:")
        print(f"   1. Train XGBoost model:")
        print(f"      curl -X POST http://localhost:8000/xgboost/train \\")
        print(f"        -H 'Content-Type: application/json' \\")
        print(f"        -d '{{")
        print(f"          \"data_source\": \"{args.output}\",")
        print(f"          \"data_format\": \"csv\",")
        print(f"          \"name\": \"{args.type}_model\",")
        print(f"          \"xgb_config\": {{")
        print(f"            \"objective\": \"{'binary:logistic' if args.type == 'classification' else 'reg:squarederror'}\"")
        print(f"          }}")
        print(f"        }}'")
        
    except Exception as e:
        print(f"❌ Error generating dataset: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main() 