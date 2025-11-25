# Heart Rate Metrics Ingestion System

A FastAPI service for ingesting and querying heart rate data from multiple devices, built with Polars and Parquet for efficient data processing.

## Features

- **High-throughput ingestion**: Handles 20,000+ readings per second with batch endpoint and buffered writes
- **Batch ingestion endpoint**: Efficient batch API for ingesting multiple readings in a single request
- **Efficient querying**: Fast time-range queries using Polars and Parquet
- **Device priority handling**: Automatically resolves conflicts when multiple devices report at the same timestamp
- **Data validation**: Validates heart rate values (30-220 bpm) and ISO 8601 timestamps
- **Concurrent write safety**: Thread-safe buffering and batching for concurrent requests
- **1-minute aggregation**: Automatically aggregates data into 1-minute buckets

## Tech Stack

- **FastAPI**: Modern, fast web framework for building APIs
- **Polars**: Lightning-fast DataFrame library for data processing
- **Parquet**: Columnar storage format optimized for analytics
- **Python 3.11+**: Modern Python with type hints throughout

## Project Structure

```
challenge-sonar-health/
├── core/
│   ├── __init__.py
│   ├── main.py          # FastAPI application
│   ├── api.py           # API endpoints (including batch endpoint)
│   ├── models.py        # Pydantic models (including batch models)
│   ├── storage.py        # Data storage service with batch ingestion
│   ├── config.py        # Configuration
│   ├── data/
│   │   └── generate_data.py  # Optimized data generator script
│   └── tests/
│       ├── test_api.py      # API endpoint tests
│       └── test_storage.py  # Storage layer tests
├── data/                # Parquet files (created at runtime)
├── docs/
│   ├── README.md        # This file
│   └── SONAR_HEALTH_TECHNICAL_CHALLENGE.md  # Challenge requirements
├── pyproject.toml      # Project configuration and dependencies (uv)
└── README.md           # Main project README
```

## Setup

1. **Install uv** (if not already installed):
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **Install dependencies**:
   ```bash
   uv sync
   ```

3. **Run the API**:
   ```bash
   uv run uvicorn core.main:app --reload
   ```
   
   Or activate the virtual environment:
   ```bash
   source .venv/bin/activate  # On macOS/Linux
   uvicorn core.main:app --reload
   ```

   The API will be available at `http://localhost:8000`

3. **View API documentation**:
   - Swagger UI: `http://localhost:8000/docs`
   - ReDoc: `http://localhost:8000/redoc`

## API Endpoints

### POST `/metrics/heart-rate`

Ingest a single heart rate metric from a device.

**Request Body**:
```json
{
  "device_id": "device_a",
  "user_id": "user_123",
  "timestamp": "2024-01-15T10:00:00Z",
  "heart_rate": 75
}
```

**Response**:
```json
{
  "status": "accepted"
}
```

**Validation**:
- Heart rate must be between 30-220 bpm
- Timestamp must be in ISO 8601 format

### POST `/metrics/heart-rate/batch`

Ingest multiple heart rate metrics in a single batch request. **Recommended for high-throughput scenarios.**

**Request Body**:
```json
{
  "readings": [
    {
      "device_id": "device_a",
      "user_id": "user_123",
      "timestamp": "2024-01-15T10:00:00Z",
      "heart_rate": 75
    },
    {
      "device_id": "device_b",
      "user_id": "user_123",
      "timestamp": "2024-01-15T10:00:01Z",
      "heart_rate": 80
    }
  ]
}
```

**Response**:
```json
{
  "status": "accepted",
  "accepted": 2,
  "rejected": 0,
  "total": 2
}
```

**Validation**:
- Maximum 1000 readings per batch
- Each reading validated individually (heart rate 30-220 bpm, valid ISO 8601 timestamp)
- Returns counts of accepted and rejected readings

**Performance**: The batch endpoint is significantly faster than individual requests, processing 400+ batches per second.

### GET `/metrics/heart-rate`

Query heart rate metrics for a user within a time range.

**Query Parameters**:
- `user_id` (required): User identifier
- `start` (required): ISO 8601 timestamp (start of range)
- `end` (required): ISO 8601 timestamp (end of range)
- `device_id` (optional): Filter by specific device

**Example**:
```
GET /metrics/heart-rate?user_id=user_123&start=2024-01-15T10:00:00Z&end=2024-01-15T10:30:00Z
```

**Response**:
```json
{
  "user_id": "user_123",
  "data": [
    {
      "timestamp": "2024-01-15T10:00:00Z",
      "heart_rate": 75.0,
      "device_id": "device_a"
    },
    {
      "timestamp": "2024-01-15T10:01:00Z",
      "heart_rate": 78.5,
      "device_id": "device_a"
    }
  ],
  "count": 2
}
```

**Features**:
- Data is aggregated into 1-minute buckets (averaged)
- Sorted by timestamp (ascending)
- Device priority resolution: when multiple devices report at the same timestamp, the highest priority device is used

### GET `/health`

Health check endpoint for monitoring.

**Response**:
```json
{
  "status": "healthy",
  "service": "heart-rate-metrics"
}
```

## Device Priority

The system handles device priority when multiple devices report heart rate at the same timestamp:

- `device_a`: Priority 1 (highest - medical grade)
- `device_b`: Priority 2 (consumer wearable)
- Unknown devices: Priority 999 (lowest)

When multiple devices report at the same 1-minute bucket, the device with the lowest priority number (highest priority) is selected.

## Design Decisions

### Data Storage

- **Parquet format**: Columnar storage optimized for analytics queries
- **Date-partitioned files**: Files are organized by date (`heart_rate_metrics_YYYY-MM-DD.parquet`) for efficient querying
- **Buffered writes**: Records are buffered in memory and written in batches to reduce I/O operations
- **Periodic flushing**: Buffer is automatically flushed every 5 seconds or when it reaches 100 records

### Concurrency

- **Async/await**: All endpoints use async/await for non-blocking I/O
- **Write locking**: Uses asyncio locks to ensure thread-safe concurrent writes
- **Batch processing**: Multiple writes are batched together to reduce file operations
- **Batch endpoint**: Optimized batch ingestion endpoint for high-throughput scenarios (20,000+ readings/second)
- **Lock optimization**: Separate locked and unlocked flush methods to prevent deadlocks

### Query Performance

- **Lazy evaluation**: Uses Polars for efficient data processing
- **Date filtering**: Only reads relevant date-partitioned files
- **Vectorized operations**: Avoids row-by-row iteration, uses Polars' vectorized operations

### Device Priority Resolution

- Priority is applied during query aggregation
- For each 1-minute bucket, the system:
  1. Groups records by minute bucket
  2. Applies device priority (lower number = higher priority)
  3. Selects the record with highest priority
  4. Averages heart rate values if needed

## Testing

### Running Tests

Install test dependencies and run tests:

```bash
# Install test dependencies
uv sync --group dev

# Run all tests
uv run pytest

# Run with verbose output
uv run pytest -v

# Run specific test file
uv run pytest tests/test_api.py
```

### Data Generator

To test the system with the optimized data generator script:

```bash
# Terminal 1: Start the API
uv run uvicorn core.main:app --reload

# Terminal 2: Run the data generator
uv run python core/data/generate_data.py

# Terminal 3: Query the data
curl "http://localhost:8000/metrics/heart-rate?user_id=user_123&start=2024-01-15T10:00:00Z&end=2024-01-15T10:30:00Z"
```

The data generator script (`core/data/generate_data.py`) will:
- Send 10,000+ heart rate readings using optimized batch endpoint
- Complete in under 1 second (vs ~2 minutes with individual requests)
- Simulate multiple devices sending data concurrently
- Include out-of-order timestamps
- Include duplicate readings
- Create burst traffic patterns
- Display real-time progress with performance metrics

**Performance**: The optimized generator achieves 20,000+ readings/second using the batch endpoint, making it ~200x faster than the original approach.

## Error Handling

The API returns appropriate HTTP status codes:

- **200 OK**: Successful query
- **202 Accepted**: Successful ingestion
- **400 Bad Request**: Invalid input (heart rate out of range, invalid timestamp format, etc.)
- **404 Not Found**: No data found for the query
- **500 Internal Server Error**: Server-side errors

## Known Limitations

1. **File-based storage**: Currently uses local Parquet files. For production, consider distributed storage (S3, HDFS, etc.)
2. **Single node**: Not designed for distributed deployment. Would need additional work for horizontal scaling
3. **No data retention**: Files are not automatically cleaned up. Consider implementing TTL policies
4. **No authentication**: API endpoints are not secured. Add authentication/authorization for production

## Future Improvements

1. **Distributed storage**: Support for cloud storage (S3, Azure Blob, etc.)
2. **Caching**: Add Redis caching for frequently queried data
3. **Metrics/observability**: Add Prometheus metrics and structured logging
4. **Database option**: Support for time-series databases (InfluxDB, TimescaleDB)
5. **API versioning**: Add versioning to API endpoints
6. **Rate limiting**: Implement rate limiting for ingestion endpoint
7. **Data compression**: Add compression options for Parquet files
8. **Partitioning**: More sophisticated partitioning (by user_id, device_id, etc.)

## License

This project is part of a technical challenge for Sonar Health.

