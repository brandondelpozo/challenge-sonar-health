"""Data storage service for handling Parquet file operations."""

import asyncio
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import polars as pl

from core.config import (
    BATCH_SIZE,
    DATA_DIR,
    DEVICE_PRIORITIES,
    FLUSH_INTERVAL_SECONDS,
    PARQUET_FILE_PREFIX,
)


class DataStorage:
    """Handles storage and retrieval of heart rate metrics using Parquet files."""

    def __init__(self):
        """Initialize the data storage service."""
        self.data_dir = Path(DATA_DIR)
        self.data_dir.mkdir(exist_ok=True)
        self.write_buffer: deque = deque(maxlen=BATCH_SIZE * 2)
        self.write_lock = asyncio.Lock()
        self._flush_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start background flush task."""
        if self._flush_task is None:
            self._flush_task = asyncio.create_task(self._periodic_flush())

    async def stop(self) -> None:
        """Stop background flush task and flush remaining data."""
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        await self._flush_buffer()

    async def ingest_metric(
        self, device_id: str, user_id: str, timestamp: str, heart_rate: int
    ) -> None:
        """Ingest a single heart rate metric."""
        # Parse timestamp to get date for file organization
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        date_str = dt.strftime("%Y-%m-%d")

        # Add to write buffer
        record = {
            "device_id": device_id,
            "user_id": user_id,
            "timestamp": timestamp,
            "heart_rate": heart_rate,
            "date": date_str,
        }

        async with self.write_lock:
            self.write_buffer.append(record)

            # Flush if buffer is full
            if len(self.write_buffer) >= BATCH_SIZE:
                await self._flush_buffer()

    async def ingest_batch(self, readings: List[Dict[str, Any]]) -> Tuple[int, int]:
        """
        Ingest multiple heart rate metrics in a batch.

        Returns:
            tuple: (accepted_count, rejected_count)
        """
        accepted = 0
        rejected = 0

        records = []
        for reading in readings:
            try:
                # Parse timestamp to get date for file organization
                dt = datetime.fromisoformat(reading["timestamp"].replace("Z", "+00:00"))
                date_str = dt.strftime("%Y-%m-%d")

                record = {
                    "device_id": reading["device_id"],
                    "user_id": reading["user_id"],
                    "timestamp": reading["timestamp"],
                    "heart_rate": reading["heart_rate"],
                    "date": date_str,
                }
                records.append(record)
                accepted += 1
            except (ValueError, KeyError):
                rejected += 1

        if records:
            async with self.write_lock:
                self.write_buffer.extend(records)

                # Flush if buffer is full (don't acquire lock again, we already have it)
                if len(self.write_buffer) >= BATCH_SIZE:
                    await self._flush_buffer_unlocked()

        return accepted, rejected

    async def flush(self) -> None:
        """Public method to force flush the buffer (useful for testing)."""
        await self._flush_buffer()

    async def _flush_buffer(self) -> None:
        """Flush buffered records to Parquet files (with lock)."""
        async with self.write_lock:
            await self._flush_buffer_unlocked()

    async def _flush_buffer_unlocked(self) -> None:
        """
        Flush buffered records to Parquet files (without lock - assumes lock is already held).

        Note: We avoid using write_parquet(mode="append") as it doesn't work reliably
        with concurrent writes. Instead, we read existing file, concatenate, and write back.
        This ensures thread-safety and data integrity.
        """
        if not self.write_buffer:
            return

        # Group records by date for efficient file organization
        # Files organized by date enable efficient querying (only read relevant date files)
        records_by_date: dict[str, List[dict]] = {}
        while self.write_buffer:
            record = self.write_buffer.popleft()
            date_str = record["date"]
            if date_str not in records_by_date:
                records_by_date[date_str] = []
            records_by_date[date_str].append(record)

        # Write each date's records to its file
        # Parquet is optimized for batch writes, not single-row appends
        # We batch writes (100 records or 5 seconds) for optimal performance
        for date_str, records in records_by_date.items():
            df = pl.DataFrame(records)
            file_path = self.data_dir / f"{PARQUET_FILE_PREFIX}_{date_str}.parquet"

            # Append to existing file or create new one
            # Note: We don't use mode="append" as it's unreliable with concurrent writes
            # Instead, read existing file, concatenate, and write back atomically
            if file_path.exists():
                existing_df = pl.read_parquet(file_path)
                combined_df = pl.concat([existing_df, df])
                combined_df.write_parquet(file_path)
            else:
                df.write_parquet(file_path)

    async def _periodic_flush(self) -> None:
        """Periodically flush the write buffer."""
        while True:
            try:
                await asyncio.sleep(FLUSH_INTERVAL_SECONDS)
                await self._flush_buffer()
            except asyncio.CancelledError:
                await self._flush_buffer()
                raise

    def query_metrics(
        self,
        user_id: str,
        start: str,
        end: str,
        device_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Query heart rate metrics for a user within a time range.

        Returns aggregated data in 1-minute buckets with device priority resolution.
        """
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))

        # Get all date files in the range
        date_files = self._get_files_in_range(start_dt, end_dt)

        if not date_files:
            return []

        # Use lazy evaluation for efficient querying
        # Scan Parquet files lazily (doesn't load into memory until needed)
        lazy_frames = []
        for file_path in date_files:
            if file_path.exists():
                lazy_frames.append(pl.scan_parquet(str(file_path)))

        if not lazy_frames:
            return []

        # Combine all lazy frames and apply filters (still lazy)
        # Filters are pushed down to Parquet scan level for optimal performance
        combined_lazy = pl.concat(lazy_frames)

        # Apply filters (lazy evaluation - filters pushed down to scan)
        filtered_lazy = combined_lazy.filter(pl.col("user_id") == user_id)

        # Filter by device_id if provided
        if device_id:
            filtered_lazy = filtered_lazy.filter(pl.col("device_id") == device_id)

        # Filter by time range
        filtered_lazy = filtered_lazy.filter(
            (pl.col("timestamp") >= start) & (pl.col("timestamp") <= end)
        )

        # Collect (execute) the lazy query
        filtered_df = filtered_lazy.collect()

        if filtered_df.is_empty():
            return []

        # Parse timestamps and create minute buckets
        # Handle both "Z" suffix and timezone offset formats
        filtered_df = filtered_df.with_columns(
            pl.col("timestamp")
            .str.replace("Z", "+00:00")
            .str.strptime(pl.Datetime, format="%Y-%m-%dT%H:%M:%S%z")
            .dt.truncate("1m")
            .alias("minute_bucket")
        )

        # Apply device priority: for each minute bucket, keep only the highest priority device
        # First, add priority column (default to 999 for unknown devices - lowest priority)
        priority_map = pl.DataFrame(
            [
                {"device_id": device, "priority": priority}
                for device, priority in DEVICE_PRIORITIES.items()
            ]
        )

        filtered_df = filtered_df.join(priority_map, on="device_id", how="left")
        # Fill null priorities with 999 (lowest priority for unknown devices)
        filtered_df = filtered_df.with_columns(
            pl.col("priority").fill_null(999)
        )

        # For each minute_bucket, keep only the record with the lowest priority number
        # (highest priority). Group by minute_bucket and user_id, then take the record
        # with minimum priority
        aggregated_df = (
            filtered_df.sort(["minute_bucket", "priority"])
            .group_by(["minute_bucket", "user_id"], maintain_order=True)
            .first()
            .group_by("minute_bucket", maintain_order=True)
            .agg(
                pl.col("heart_rate").mean().round(2).alias("heart_rate"),
                pl.col("device_id").first().alias("device_id"),
            )
            .with_columns(
                pl.col("minute_bucket")
                .dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                .alias("timestamp")
            )
            .drop("minute_bucket")
            .sort("timestamp")
        )

        # Convert to list of dictionaries
        return aggregated_df.to_dicts()

    def _get_files_in_range(
        self, start_dt: datetime, end_dt: datetime
    ) -> List[Path]:
        """Get all Parquet files that might contain data in the given date range."""
        files = []
        current_date = start_dt.date()
        end_date = end_dt.date()

        while current_date <= end_date:
            file_path = (
                self.data_dir / f"{PARQUET_FILE_PREFIX}_{current_date.isoformat()}.parquet"
            )
            if file_path.exists():
                files.append(file_path)
            # Move to next day
            current_date = current_date + timedelta(days=1)

        return files

