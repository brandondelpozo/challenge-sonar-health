"""Tests for API endpoints."""

import asyncio
import time

from fastapi.testclient import TestClient

from core.api import storage
from core.main import app

client = TestClient(app)


def test_health_check():
    """Test health check endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "heart-rate-metrics"


def test_ingest_valid_heart_rate():
    """Test ingesting a valid heart rate reading."""
    response = client.post(
        "/metrics/heart-rate",
        json={
            "device_id": "device_a",
            "user_id": "user_123",
            "timestamp": "2024-01-15T10:00:00Z",
            "heart_rate": 75,
        },
    )
    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "accepted"


def test_ingest_invalid_heart_rate_too_low():
    """Test ingesting heart rate below minimum."""
    response = client.post(
        "/metrics/heart-rate",
        json={
            "device_id": "device_a",
            "user_id": "user_123",
            "timestamp": "2024-01-15T10:00:00Z",
            "heart_rate": 25,  # Below minimum of 30
        },
    )
    assert response.status_code == 422  # Validation error


def test_ingest_invalid_heart_rate_too_high():
    """Test ingesting heart rate above maximum."""
    response = client.post(
        "/metrics/heart-rate",
        json={
            "device_id": "device_a",
            "user_id": "user_123",
            "timestamp": "2024-01-15T10:00:00Z",
            "heart_rate": 250,  # Above maximum of 220
        },
    )
    assert response.status_code == 422  # Validation error


def test_ingest_invalid_timestamp():
    """Test ingesting with invalid timestamp format."""
    response = client.post(
        "/metrics/heart-rate",
        json={
            "device_id": "device_a",
            "user_id": "user_123",
            "timestamp": "invalid-timestamp",
            "heart_rate": 75,
        },
    )
    assert response.status_code == 422  # Validation error


def test_query_no_data():
    """Test querying when no data exists."""
    response = client.get(
        "/metrics/heart-rate",
        params={
            "user_id": "nonexistent_user",
            "start": "2024-01-15T10:00:00Z",
            "end": "2024-01-15T10:30:00Z",
        },
    )
    assert response.status_code == 404


def test_query_invalid_date_range():
    """Test querying with invalid date range."""
    response = client.get(
        "/metrics/heart-rate",
        params={
            "user_id": "user_123",
            "start": "2024-01-15T10:30:00Z",  # Start after end
            "end": "2024-01-15T10:00:00Z",
        },
    )
    assert response.status_code == 400


def test_query_with_data(capsys):
    """Test querying with actual data."""
    start_time = time.time()
    print("\n" + "=" * 60)
    print("Starting test_query_with_data")
    print("=" * 60)

    # First, ingest some data
    print("→ Ingesting first heart rate reading...")
    ingest1_start = time.time()
    response1 = client.post(
        "/metrics/heart-rate",
        json={
            "device_id": "device_a",
            "user_id": "test_user",
            "timestamp": "2024-01-15T10:00:00Z",
            "heart_rate": 75,
        },
    )
    ingest1_time = time.time() - ingest1_start
    assert response1.status_code == 202, f"Expected 202, got {response1.status_code}"
    print(f"  ✓ First ingestion completed in {ingest1_time:.3f}s")

    print("→ Ingesting second heart rate reading...")
    ingest2_start = time.time()
    response2 = client.post(
        "/metrics/heart-rate",
        json={
            "device_id": "device_a",
            "user_id": "test_user",
            "timestamp": "2024-01-15T10:01:00Z",
            "heart_rate": 78,
        },
    )
    ingest2_time = time.time() - ingest2_start
    assert response2.status_code == 202, f"Expected 202, got {response2.status_code}"
    print(f"  ✓ Second ingestion completed in {ingest2_time:.3f}s")

    # Force flush the buffer to ensure data is written
    print("→ Flushing buffer to disk...")
    flush_start = time.time()
    # Use a new event loop to avoid conflicts
    try:
        asyncio.get_running_loop()
        # If loop is running, create a new one in a thread
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, storage.flush())
            future.result(timeout=10)
    except RuntimeError:
        # No event loop exists, create one
        asyncio.run(storage.flush())
    flush_time = time.time() - flush_start
    print(f"  ✓ Flush completed in {flush_time:.3f}s")

    # Query the data
    print("→ Querying data...")
    query_start = time.time()
    response = client.get(
        "/metrics/heart-rate",
        params={
            "user_id": "test_user",
            "start": "2024-01-15T10:00:00Z",
            "end": "2024-01-15T10:05:00Z",
        },
    )
    query_time = time.time() - query_start
    print(f"  ✓ Query completed in {query_time:.3f}s")

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert data["user_id"] == "test_user"
    assert len(data["data"]) > 0, f"Expected data, got {data}"
    assert data["count"] > 0

    total_time = time.time() - start_time
    print("-" * 60)
    print(f"✓ test_query_with_data completed in {total_time:.3f}s total")
    print(f"✓ Found {data['count']} data points")
    print("=" * 60 + "\n")


def test_device_priority(capsys):
    """Test that device priority is respected when multiple devices report."""
    start_time = time.time()
    print("\n" + "=" * 60)
    print("Starting test_device_priority")
    print("=" * 60)

    # Send data from multiple devices at the same timestamp
    print("→ Sending data from device_b (lower priority, priority=2)...")
    client.post(
        "/metrics/heart-rate",
        json={
            "device_id": "device_b",  # Lower priority
            "user_id": "priority_test",
            "timestamp": "2024-01-15T10:00:00Z",
            "heart_rate": 80,
        },
    )
    print("→ Sending data from device_a (higher priority, priority=1)...")
    client.post(
        "/metrics/heart-rate",
        json={
            "device_id": "device_a",  # Higher priority
            "user_id": "priority_test",
            "timestamp": "2024-01-15T10:00:00Z",
            "heart_rate": 75,
        },
    )

    # Force flush the buffer to ensure data is written
    print("→ Flushing buffer...")
    flush_start = time.time()
    asyncio.run(storage.flush())
    print(f"  ✓ Flush completed in {time.time() - flush_start:.3f}s")

    # Query and verify device_a (higher priority) is used
    print("→ Querying data to verify priority...")
    query_start = time.time()
    response = client.get(
        "/metrics/heart-rate",
        params={
            "user_id": "priority_test",
            "start": "2024-01-15T10:00:00Z",
            "end": "2024-01-15T10:01:00Z",
        },
    )
    query_time = time.time() - query_start
    print(f"  ✓ Query completed in {query_time:.3f}s")

    assert response.status_code == 200
    data = response.json()
    # Should have device_a (priority 1) not device_b (priority 2)
    if len(data["data"]) > 0:
        # The device with higher priority should be selected
        assert data["data"][0]["device_id"] == "device_a"
        print("  ✓ Priority test passed: device_a selected (priority 1)")

    total_time = time.time() - start_time
    print("-" * 60)
    print(f"✓ test_device_priority completed in {total_time:.3f}s")
    print("=" * 60 + "\n")

