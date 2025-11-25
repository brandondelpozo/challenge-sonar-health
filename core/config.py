"""Configuration settings for the heart rate metrics system."""

from typing import Dict

# Device priority configuration
# Lower number = higher priority
DEVICE_PRIORITIES: Dict[str, int] = {
    "device_a": 1,  # Medical grade (highest priority)
    "device_b": 2,  # Consumer wearable
}

# Heart rate validation bounds
MIN_HEART_RATE = 30
MAX_HEART_RATE = 220

# Data storage configuration
DATA_DIR = "data"
PARQUET_FILE_PREFIX = "heart_rate_metrics"

# Batch write configuration (for performance)
BATCH_SIZE = 100  # Number of records to buffer before writing
FLUSH_INTERVAL_SECONDS = 5  # Flush buffer every N seconds

