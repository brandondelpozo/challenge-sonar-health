# Heart Rate Metrics Ingestion System

A high-performance FastAPI service for ingesting and querying heart rate data from multiple devices, built with Polars and Parquet for efficient data processing.

## Setup/Installation Instructions

### Prerequisites

- Python 3.11 or higher
- [uv](https://github.com/astral-sh/uv) package manager (recommended) or pip

### Installation

```bash
# Clone the repository
git clone https://github.com/brandondelpozo/challenge-sonar-health
cd challenge-sonar-health

# Install dependencies using uv (recommended)
uv sync

# Or using pip
pip install -e .
```

### Dependencies

The project uses minimal dependencies as required:

- **fastapi** - Web framework for building APIs
- **uvicorn** - ASGI server for running FastAPI
- **polars** - High-performance DataFrame library
- **pydantic** - Data validation and settings management

Optional dependencies (for development/testing):
- **pytest** - Testing framework
- **pytest-asyncio** - Async test support
- **httpx** - HTTP client (used by data generator script)

## How to Run the API

### Start the Server

```bash
# Using uv (recommended)
uv run uvicorn core.main:app --reload --host 0.0.0.0 --port 8000

# Or using uvicorn directly (if installed globally)
uvicorn core.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at:
- **API**: http://localhost:8000
- **Interactive API Docs**: http://localhost:8000/docs
- **OpenAPI Schema**: http://localhost:8000/openapi.json

### Example Usage

```bash
# Health check
curl http://localhost:8000/health

# Ingest a single heart rate reading
curl -X POST http://localhost:8000/metrics/heart-rate \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": "device_a",
    "user_id": "user_123",
    "timestamp": "2024-01-15T10:00:00Z",
    "heart_rate": 75
  }'

# Query heart rate data
curl "http://localhost:8000/metrics/heart-rate?user_id=user_123&start=2024-01-15T10:00:00Z&end=2024-01-15T10:30:00Z"
```

### Generate Test Data

The project includes a data generator script for testing:

```bash
# Terminal 1: Start the API (see above)

# Terminal 2: Run the data generator
uv run python core/data/generate_data.py
```

This will generate and send 10,000+ heart rate readings using the optimized batch endpoint.

## How to Run Tests

```bash
# Run all tests
uv run pytest

# Run with verbose output
uv run pytest -v

# Run specific test file
uv run pytest core/tests/test_api.py

# Run with coverage (if pytest-cov is installed)
uv run pytest --cov=core --cov-report=html
```

### Test Coverage

The test suite includes:
- API endpoint tests (validation, error handling, device priority)
- Storage layer tests (ingestion, querying, aggregation)
- Integration tests with real data

All tests pass (12/12) and cover:
- ✅ Valid and invalid data ingestion
- ✅ Query operations with various filters
- ✅ Error handling (400, 404, 422, 500)
- ✅ Device priority resolution
- ✅ Concurrent operations

## Project Structure

```
challenge-sonar-health/
├── core/                    # Main application code
│   ├── __init__.py
│   ├── main.py              # FastAPI application entry point
│   ├── api.py               # API endpoints (POST/GET routes)
│   ├── models.py            # Pydantic models for request/response
│   ├── storage.py           # Data storage service (Polars/Parquet)
│   ├── config.py            # Configuration constants
│   ├── data/
│   │   └── generate_data.py # Test data generator script
│   └── tests/               # Test suite
│       ├── test_api.py      # API endpoint tests
│       └── test_storage.py  # Storage layer tests
├── docs/                    # Documentation
│   ├── README.md            # Detailed API documentation
│   └── SONAR_HEALTH_TECHNICAL_CHALLENGE.md  # Challenge requirements
├── data/                    # Parquet data files (created at runtime)
├── pyproject.toml           # Project configuration and dependencies
├── uv.lock                  # Dependency lock file (uv)
└── README.md               # This file
```

## Design Decisions and Trade-offs

### 1. **Storage Format: Parquet over Database**

**Decision**: Use Parquet files organized by date instead of a traditional database.

**Rationale**:
- **Performance**: Parquet's columnar format is optimized for analytical queries
- **Simplicity**: No database setup required, easy to deploy
- **Cost**: No database server overhead
- **Scalability**: Can easily migrate to object storage (S3, GCS) later

**Trade-offs**:
- ✅ Excellent for read-heavy analytical workloads
- ⚠️ Less optimal for frequent small writes (mitigated by buffering)
- ⚠️ No ACID transactions (acceptable for metrics ingestion)

### 2. **Buffered Writes with Periodic Flushing**

**Decision**: Buffer writes in memory and flush periodically (every 5 seconds or 100 records).

**Rationale**:
- **Performance**: Reduces I/O operations significantly
- **Throughput**: Enables 20,000+ readings/second
- **Efficiency**: Batches multiple writes into single file operations

**Trade-offs**:
- ✅ High throughput and reduced I/O
- ⚠️ Risk of data loss on crash (mitigated by frequent flushing)
- ⚠️ Slight delay in data availability (max 5 seconds)

### 3. **Batch Endpoint for High Throughput**

**Decision**: Implement a dedicated batch ingestion endpoint (`/metrics/heart-rate/batch`).

**Rationale**:
- **Performance**: 200x faster than individual requests
- **Network Efficiency**: Reduces HTTP overhead
- **Scalability**: Handles high-volume scenarios

**Trade-offs**:
- ✅ Massive performance improvement
- ⚠️ Slightly more complex API (two endpoints instead of one)
- ✅ Backward compatible (single endpoint still available)

### 4. **Device Priority Resolution at Query Time**

**Decision**: Resolve device priority conflicts during query aggregation, not at ingestion.

**Rationale**:
- **Flexibility**: Priority rules can change without reprocessing data
- **Storage Efficiency**: Don't duplicate or discard data at ingestion
- **Query Performance**: Polars efficiently handles aggregation

**Trade-offs**:
- ✅ More flexible and storage-efficient
- ⚠️ Slightly more complex query logic
- ✅ Better for analytics (all data preserved)

### 5. **1-Minute Aggregation Buckets**

**Decision**: Aggregate data into 1-minute buckets during queries.

**Rationale**:
- **Reduces Data Volume**: Handles high-frequency readings efficiently
- **Standard Practice**: Common in time-series analytics
- **Performance**: Faster queries with less data to transfer

**Trade-offs**:
- ✅ Efficient for most use cases
- ⚠️ Loses sub-minute granularity (acceptable for heart rate metrics)

### 6. **Async/Await Throughout**

**Decision**: Use async/await patterns for all I/O operations.

**Rationale**:
- **Concurrency**: Handle multiple requests efficiently
- **Performance**: Non-blocking I/O operations
- **Scalability**: Better resource utilization

**Trade-offs**:
- ✅ Excellent for concurrent workloads
- ⚠️ Slightly more complex code (worth it for performance)

### 7. **Polars over Pandas**

**Decision**: Use Polars instead of Pandas for DataFrame operations.

**Rationale**:
- **Performance**: 5-10x faster than Pandas
- **Memory Efficiency**: Better memory management
- **Modern API**: Cleaner, more intuitive API

**Trade-offs**:
- ✅ Significantly faster
- ⚠️ Less ecosystem support (acceptable for this use case)

### 8. **Type Hints Throughout**

**Decision**: Use comprehensive type hints for all functions and methods.

**Rationale**:
- **Code Quality**: Better IDE support and error detection
- **Maintainability**: Self-documenting code
- **Modern Python**: Best practice for Python 3.11+

**Trade-offs**:
- ✅ Better developer experience
- ⚠️ Slightly more verbose (worth it for clarity)

## Known Limitations

1. **Data Persistence**: Data is stored in local Parquet files. For production, consider:
   - Object storage (S3, GCS) for scalability
   - Distributed file systems for multi-server deployments

2. **Concurrent Writes**: While thread-safe, very high concurrent write loads might benefit from:
   - Distributed locking mechanism
   - Message queue for ingestion (Kafka, RabbitMQ)

3. **Query Performance**: Large date ranges (>30 days) might be slow. Consider:
   - Partitioning by month/year
   - Indexing strategies
   - Query result caching

4. **Data Retention**: No automatic data cleanup. For production:
   - Implement TTL (time-to-live) policies
   - Archive old data to cold storage

5. **Authentication/Authorization**: Currently no authentication. For production:
   - Add API key or OAuth authentication
   - Implement user-level access control

6. **Monitoring**: No built-in metrics/monitoring. Consider:
   - Prometheus metrics
   - Health check endpoints (basic one exists)
   - Logging infrastructure

## Future Improvements

1. **Distributed Storage**: Migrate to object storage (S3, GCS) for multi-server deployments
2. **Caching Layer**: Add Redis for frequently queried data
3. **Streaming Ingestion**: Implement Kafka/RabbitMQ for even higher throughput
4. **Advanced Aggregations**: Support different time buckets (5min, 15min, 1hour)
5. **Data Compression**: Implement compression for Parquet files
6. **Query Optimization**: Add query result caching and query planning
7. **Authentication**: Add API key or OAuth authentication
8. **Rate Limiting**: Implement rate limiting per user/device
9. **Data Validation**: More sophisticated validation (anomaly detection)
10. **Monitoring**: Add Prometheus metrics and structured logging
11. **Multi-tenancy**: Support multiple organizations/tenants
12. **GraphQL API**: Add GraphQL endpoint for flexible queries

## API Endpoints

- `POST /metrics/heart-rate` - Ingest a single heart rate reading
- `POST /metrics/heart-rate/batch` - Ingest multiple readings in one request (recommended for high throughput)
- `GET /metrics/heart-rate` - Query heart rate data with time range filtering
- `GET /health` - Health check endpoint

See [docs/README.md](docs/README.md) for complete API documentation.

## Performance

The optimized batch endpoint achieves:
- **20,000+ readings/second** ingestion rate
- **400+ batches/second** processing
- **Sub-second** completion for 10,000 readings
- **~200x faster** than individual requests

## Tech Stack

- **FastAPI** - Modern async web framework
- **Polars** - Lightning-fast DataFrame library
- **Parquet** - Columnar storage format
- **Python 3.11+** - Modern Python with type hints
- **Pydantic** - Data validation

## License

This project is part of a technical challenge for Sonar Health.
