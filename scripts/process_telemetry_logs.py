#!/usr/bin/env python3
"""
Telemetry Log Processing Script for XGBoost Training

This script processes organ telemetry logs and converts them into training datasets
for XGBoost models, as specified in Method 3 of the XGBoost integration instructions.

The script reads JSON logs from organ operations and flattens them into CSV format
suitable for XGBoost training.

Usage:
    docker exec -it seedcore-ray-head python /app/scripts/process_telemetry_logs.py
"""

import json
import glob
import pandas as pd
import numpy as np
import os
import sys
import argparse
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_telemetry_logs(log_pattern: str = "/var/log/organ/*.jsonl") -> List[Dict[str, Any]]:
    """
    Load telemetry logs from the specified pattern.
    
    Args:
        log_pattern: Glob pattern for log files
        
    Returns:
        List of parsed log records
    """
    records = []
    log_files = glob.glob(log_pattern)
    
    if not log_files:
        logger.warning(f"No log files found matching pattern: {log_pattern}")
        # Create sample data for testing if no logs exist
        return create_sample_telemetry_data()
    
    logger.info(f"Found {len(log_files)} log files")
    
    for log_file in log_files:
        try:
            logger.info(f"Processing log file: {log_file}")
            with open(log_file, 'r') as f:
                for line_num, line in enumerate(f, 1):
                    try:
                        if line.strip():
                            doc = json.loads(line.strip())
                            records.append(doc)
                    except json.JSONDecodeError as e:
                        logger.warning(f"Invalid JSON in {log_file}:{line_num}: {e}")
                        continue
        except Exception as e:
            logger.error(f"Error reading log file {log_file}: {e}")
            continue
    
    logger.info(f"Loaded {len(records)} log records")
    return records


def create_sample_telemetry_data(n_samples: int = 1000) -> List[Dict[str, Any]]:
    """
    Create sample telemetry data for testing when no real logs are available.
    
    Args:
        n_samples: Number of sample records to generate
        
    Returns:
        List of sample telemetry records
    """
    logger.info(f"Creating {n_samples} sample telemetry records for testing")
    
    records = []
    organs = ["cognitive", "utility", "actuator", "sensory"]
    paths = ["fast", "slow", "memory", "energy"]
    
    np.random.seed(42)
    
    for i in range(n_samples):
        # Generate realistic telemetry data
        record = {
            "task_id": f"task_{i:06d}",
            "organ": np.random.choice(organs),
            "path": np.random.choice(paths),
            "energy": {
                "pair": np.random.beta(2, 5),
                "hyper": np.random.beta(1, 3),
                "entropy": np.random.normal(-0.02, 0.05),
                "reg": np.random.beta(1, 4),
                "mem": np.random.beta(2, 3),
                "total": 0.0  # Will be calculated
            },
            "memory_stats": {
                "mw_hits": np.random.poisson(3),
                "mlt_hits": np.random.poisson(1),
                "compr_ratio": np.random.uniform(1.2, 2.5)
            },
            "capability": {
                "a7": np.random.beta(3, 2)
            },
            "timestamp": (datetime.now() - timedelta(seconds=np.random.randint(0, 86400))).isoformat()
        }
        
        # Calculate total energy
        energy = record["energy"]
        energy["total"] = energy["pair"] + energy["hyper"] + energy["entropy"] + energy["reg"] + energy["mem"]
        
        records.append(record)
    
    return records


def flatten_telemetry_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Flatten a nested telemetry record into a flat structure.
    
    Args:
        record: Nested telemetry record
        
    Returns:
        Flattened record
    """
    flat_record = {
        "task_id": record.get("task_id", ""),
        "organ": record.get("organ", ""),
        "path": record.get("path", ""),
        "timestamp": record.get("timestamp", ""),
    }
    
    # Flatten energy data
    energy = record.get("energy", {})
    for key, value in energy.items():
        flat_record[f"energy_{key}"] = value
    
    # Flatten memory stats
    memory_stats = record.get("memory_stats", {})
    for key, value in memory_stats.items():
        flat_record[f"memory_{key}"] = value
    
    # Flatten capability data
    capability = record.get("capability", {})
    for key, value in capability.items():
        flat_record[f"capability_{key}"] = value
    
    return flat_record


def create_training_targets(records: List[Dict[str, Any]], target_type: str = "energy_total") -> pd.DataFrame:
    """
    Create training targets from telemetry records.
    
    Args:
        records: List of telemetry records
        target_type: Type of target to create
        
    Returns:
        DataFrame with features and target
    """
    logger.info(f"Creating training dataset with target: {target_type}")
    
    # Flatten all records
    flattened_records = [flatten_telemetry_record(record) for record in records]
    df = pd.DataFrame(flattened_records)
    
    # Create target based on target_type
    if target_type == "energy_total":
        df["target"] = df["energy_total"]
    elif target_type == "path_fast":
        # Binary classification: path == "fast"
        df["target"] = (df["path"] == "fast").astype(int)
    elif target_type == "risk_score":
        # Risk score based on energy components
        df["target"] = (
            0.3 * df["energy_pair"] +
            0.2 * df["energy_mem"] +
            0.15 * df["energy_reg"] +
            0.1 * df["energy_hyper"] +
            0.05 * df["energy_entropy"]
        )
        # Normalize to [0, 1]
        df["target"] = (df["target"] - df["target"].min()) / (df["target"].max() - df["target"].min())
    elif target_type == "success_probability":
        # Success probability based on capability and energy
        df["target"] = (
            0.4 * df["capability_a7"] +
            0.3 * (1 - df["energy_total"]) +
            0.2 * (1 - df["memory_compr_ratio"] / 3) +
            0.1 * (df["memory_mw_hits"] / 10)
        )
        df["target"] = np.clip(df["target"], 0, 1)
    else:
        raise ValueError(f"Unknown target type: {target_type}")
    
    # Remove non-feature columns
    feature_columns = [col for col in df.columns if col not in ["task_id", "timestamp", "target"]]
    
    # One-hot encode categorical features
    categorical_columns = ["organ", "path"]
    df_encoded = pd.get_dummies(df, columns=categorical_columns, dummy_na=True)
    
    # Ensure all expected columns exist
    expected_organs = ["organ_cognitive", "organ_utility", "organ_actuator", "organ_sensory"]
    expected_paths = ["path_fast", "path_slow", "path_memory", "path_energy"]
    
    for col in expected_organs + expected_paths:
        if col not in df_encoded.columns:
            df_encoded[col] = 0
    
    # Reorder columns to put target last
    feature_cols = [col for col in df_encoded.columns if col != "target"]
    df_encoded = df_encoded[feature_cols + ["target"]]
    
    logger.info(f"Created training dataset with {len(df_encoded)} samples and {len(feature_cols)} features")
    logger.info(f"Target statistics: min={df_encoded['target'].min():.3f}, max={df_encoded['target'].max():.3f}, mean={df_encoded['target'].mean():.3f}")
    
    return df_encoded


def main():
    """Main function to process telemetry logs."""
    parser = argparse.ArgumentParser(description="Process telemetry logs for XGBoost training")
    parser.add_argument("--log-pattern", type=str, default="/var/log/organ/*.jsonl",
                       help="Glob pattern for log files")
    parser.add_argument("--target-type", choices=["energy_total", "path_fast", "risk_score", "success_probability"],
                       default="energy_total", help="Type of target to create")
    parser.add_argument("--output", type=str, default="/data/telemetry_training.csv",
                       help="Output CSV file path")
    parser.add_argument("--sample-size", type=int, default=1000,
                       help="Number of sample records to generate if no logs found")
    
    args = parser.parse_args()
    
    print(f"🎯 Processing telemetry logs for XGBoost training...")
    print(f"   Log pattern: {args.log_pattern}")
    print(f"   Target type: {args.target_type}")
    print(f"   Output: {args.output}")
    print()
    
    try:
        # Load telemetry logs
        records = load_telemetry_logs(args.log_pattern)
        
        if not records:
            logger.error("No telemetry records found")
            sys.exit(1)
        
        # Create training dataset
        df = create_training_targets(records, args.target_type)
        
        # Ensure output directory exists
        os.makedirs(os.path.dirname(args.output), exist_ok=True)
        
        # Save to CSV
        df.to_csv(args.output, index=False)
        
        print(f"✅ Telemetry training dataset saved to: {args.output}")
        print(f"   Samples: {len(df)}")
        print(f"   Features: {len(df.columns) - 1}")
        print(f"   Target: {args.target_type}")
        print(f"   File size: {os.path.getsize(args.output) / 1024 / 1024:.2f} MB")
        
        # Print feature information
        feature_cols = [col for col in df.columns if col != "target"]
        print(f"\n📊 Feature breakdown:")
        print(f"   Energy features: {len([col for col in feature_cols if col.startswith('energy_')])}")
        print(f"   Memory features: {len([col for col in feature_cols if col.startswith('memory_')])}")
        print(f"   Capability features: {len([col for col in feature_cols if col.startswith('capability_')])}")
        print(f"   Organ features: {len([col for col in feature_cols if col.startswith('organ_')])}")
        print(f"   Path features: {len([col for col in feature_cols if col.startswith('path_')])}")
        
        # Print next steps
        print(f"\n📋 Next steps:")
        print(f"   1. Train XGBoost model:")
        print(f"      curl -X POST http://localhost:8000/xgboost/train \\")
        print(f"        -H 'Content-Type: application/json' \\")
        print(f"        -d '{{")
        print(f"          \"data_source\": \"{args.output}\",")
        print(f"          \"data_format\": \"csv\",")
        print(f"          \"name\": \"telemetry_{args.target_type}_model\",")
        print(f"          \"xgb_config\": {{")
        if args.target_type == "path_fast":
            print(f"            \"objective\": \"binary:logistic\"")
        else:
            print(f"            \"objective\": \"reg:squarederror\"")
        print(f"          }}")
        print(f"        }}'")
        
        print(f"\n   2. Use the model in UtilityPredictor actor:")
        print(f"      from src.seedcore.agents.utility_inference_actor import get_utility_predictor")
        print(f"      predictor = get_utility_predictor()")
        print(f"      prediction = ray.get(predictor.predict.remote(features))")
        
    except Exception as e:
        logger.error(f"Error processing telemetry logs: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main() 