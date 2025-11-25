"""Pydantic models for request and response validation."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class HeartRateMetricRequest(BaseModel):
    """Request model for heart rate data ingestion."""

    device_id: str = Field(..., description="Device identifier")
    user_id: str = Field(..., description="User identifier")
    timestamp: str = Field(..., description="ISO 8601 timestamp")
    heart_rate: int = Field(..., description="Heart rate in bpm")

    @field_validator("heart_rate")
    @classmethod
    def validate_heart_rate(cls, v: int) -> int:
        """Validate heart rate is within acceptable range."""
        from core.config import MAX_HEART_RATE, MIN_HEART_RATE

        if not (MIN_HEART_RATE <= v <= MAX_HEART_RATE):
            raise ValueError(
                f"Heart rate must be between {MIN_HEART_RATE} and {MAX_HEART_RATE} bpm"
            )
        return v

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, v: str) -> str:
        """Validate timestamp is valid ISO 8601 format."""
        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("Timestamp must be in ISO 8601 format")
        return v


class HeartRateDataPoint(BaseModel):
    """Individual heart rate data point in response."""

    timestamp: str = Field(..., description="ISO 8601 timestamp")
    heart_rate: float = Field(..., description="Average heart rate in bpm")
    device_id: Optional[str] = Field(None, description="Device identifier")


class HeartRateResponse(BaseModel):
    """Response model for heart rate data query."""

    user_id: str = Field(..., description="User identifier")
    data: List[HeartRateDataPoint] = Field(..., description="Aggregated heart rate data")
    count: int = Field(..., description="Number of data points returned")


class StatusResponse(BaseModel):
    """Response model for data ingestion."""

    status: str = Field(default="accepted", description="Ingestion status")


class HeartRateBatchRequest(BaseModel):
    """Request model for batch heart rate data ingestion."""

    readings: List[HeartRateMetricRequest] = Field(..., description="List of heart rate readings")

    @field_validator("readings")
    @classmethod
    def validate_readings(cls, v: List[HeartRateMetricRequest]) -> List[HeartRateMetricRequest]:
        """Validate batch size is reasonable."""
        if len(v) > 1000:
            raise ValueError("Batch size cannot exceed 1000 readings")
        if len(v) == 0:
            raise ValueError("Batch must contain at least one reading")
        return v


class BatchStatusResponse(BaseModel):
    """Response model for batch data ingestion."""

    status: str = Field(default="accepted", description="Batch ingestion status")
    accepted: int = Field(..., description="Number of readings accepted")
    rejected: int = Field(..., description="Number of readings rejected")
    total: int = Field(..., description="Total number of readings in batch")

