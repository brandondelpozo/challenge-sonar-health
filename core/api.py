"""FastAPI endpoints for heart rate metrics."""

from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncIterator, Optional

from fastapi import APIRouter, FastAPI, HTTPException, status

from core.models import (
    BatchStatusResponse,
    HeartRateBatchRequest,
    HeartRateDataPoint,
    HeartRateMetricRequest,
    HeartRateResponse,
    StatusResponse,
)
from core.storage import DataStorage

router = APIRouter()
storage = DataStorage()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Lifespan context manager for startup and shutdown."""
    # Startup
    await storage.start()
    yield
    # Shutdown
    await storage.stop()


@router.post(
    "/metrics/heart-rate",
    response_model=StatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest heart rate metric",
    description="Store a heart rate reading from a device",
)
async def ingest_heart_rate(metric: HeartRateMetricRequest) -> StatusResponse:
    """
    Ingest a heart rate metric from a device.

    Validates the heart rate value (30-220 bpm) and stores it in Parquet format.
    Handles concurrent writes safely using buffering and batching.
    """
    try:
        await storage.ingest_metric(
            device_id=metric.device_id,
            user_id=metric.user_id,
            timestamp=metric.timestamp,
            heart_rate=metric.heart_rate,
        )
        return StatusResponse(status="accepted")
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}",
        )


@router.get(
    "/metrics/heart-rate",
    response_model=HeartRateResponse,
    summary="Query heart rate metrics",
    description="Retrieve aggregated heart rate data for a user within a time range",
)
async def query_heart_rate(
    user_id: str,
    start: str,
    end: str,
    device_id: Optional[str] = None,
) -> HeartRateResponse:
    """
    Query heart rate metrics for a user within a time range.

    Returns data aggregated into 1-minute buckets, sorted by timestamp.
    When multiple devices report at the same timestamp, uses the device with highest priority.
    """
    # Validate timestamps
    try:
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid timestamp format. Use ISO 8601 format (e.g., 2024-01-15T10:00:00Z)",
        )

    # Validate date range
    if start_dt >= end_dt:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Start timestamp must be before end timestamp",
        )

    try:
        # Query data from storage
        data = storage.query_metrics(
            user_id=user_id,
            start=start,
            end=end,
            device_id=device_id,
        )

        if not data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No heart rate data found for user {user_id} in the specified time range",
            )

        # Convert to response format
        data_points = [
            HeartRateDataPoint(
                timestamp=record["timestamp"],
                heart_rate=record["heart_rate"],
                device_id=record.get("device_id"),
            )
            for record in data
        ]

        return HeartRateResponse(
            user_id=user_id,
            data=data_points,
            count=len(data_points),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}",
        )


@router.post(
    "/metrics/heart-rate/batch",
    response_model=BatchStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Batch ingest heart rate metrics",
    description="Store multiple heart rate readings in a single request",
)
async def ingest_heart_rate_batch(batch: HeartRateBatchRequest) -> BatchStatusResponse:
    """
    Ingest multiple heart rate metrics in a batch.

    More efficient than individual requests for high-throughput scenarios.
    Validates all readings and returns counts of accepted/rejected items.
    """
    try:
        # Convert Pydantic models to dicts for storage
        readings_data = [
            {
                "device_id": reading.device_id,
                "user_id": reading.user_id,
                "timestamp": reading.timestamp,
                "heart_rate": reading.heart_rate,
            }
            for reading in batch.readings
        ]

        accepted, rejected = await storage.ingest_batch(readings_data)

        return BatchStatusResponse(
            status="accepted",
            accepted=accepted,
            rejected=rejected,
            total=len(batch.readings),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid batch data: {str(e)}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}",
        )


@router.get("/health", summary="Health check endpoint")
async def health_check() -> dict[str, str]:
    """Health check endpoint for monitoring."""
    return {"status": "healthy", "service": "heart-rate-metrics"}

