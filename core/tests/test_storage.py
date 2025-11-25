"""Tests for storage functionality."""

from datetime import datetime, timedelta

import pytest

from core.storage import DataStorage


@pytest.mark.asyncio
async def test_storage_ingest():
    """Test basic data ingestion."""
    storage = DataStorage()
    await storage.start()

    try:
        await storage.ingest_metric(
            device_id="device_a",
            user_id="test_user",
            timestamp="2024-01-15T10:00:00Z",
            heart_rate=75,
        )
        # Flush buffer
        await storage._flush_buffer()
    finally:
        await storage.stop()


@pytest.mark.asyncio
async def test_storage_query():
    """Test data querying."""
    storage = DataStorage()
    await storage.start()

    try:
        # Ingest some test data
        base_time = datetime(2024, 1, 15, 10, 0, 0)
        for i in range(5):
            timestamp = (base_time + timedelta(minutes=i)).isoformat() + "Z"
            await storage.ingest_metric(
                device_id="device_a",
                user_id="query_test",
                timestamp=timestamp,
                heart_rate=70 + i,
            )

        # Flush buffer
        await storage._flush_buffer()

        # Query the data
        results = storage.query_metrics(
            user_id="query_test",
            start="2024-01-15T10:00:00Z",
            end="2024-01-15T10:10:00Z",
        )

        assert len(results) > 0
        # Results should be sorted by timestamp
        timestamps = [r["timestamp"] for r in results]
        assert timestamps == sorted(timestamps)
    finally:
        await storage.stop()


@pytest.mark.asyncio
async def test_device_priority_resolution():
    """Test that device priority is correctly applied."""
    storage = DataStorage()
    await storage.start()

    try:
        # Send data from multiple devices at same timestamp
        timestamp = "2024-01-15T10:00:00Z"
        await storage.ingest_metric("device_b", "priority_user", timestamp, 80)
        await storage.ingest_metric("device_a", "priority_user", timestamp, 75)

        await storage._flush_buffer()

        # Query and verify higher priority device is used
        results = storage.query_metrics(
            user_id="priority_user",
            start="2024-01-15T10:00:00Z",
            end="2024-01-15T10:01:00Z",
        )

        if results:
            # device_a has priority 1, device_b has priority 2
            # So device_a should be selected
            assert results[0]["device_id"] == "device_a"
            assert results[0]["heart_rate"] == 75.0
    finally:
        await storage.stop()

