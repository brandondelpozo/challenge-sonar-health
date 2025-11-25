"""Data generator script for testing the heart rate metrics API.

Sends 10,000 heart rate readings with optimized batch processing:
- Multiple devices sending data concurrently
- Out-of-order timestamps
- Duplicate readings
- Burst traffic patterns
- Batch API endpoint for maximum performance
"""

import asyncio
import importlib.util
import json
import random
import time
from datetime import datetime, timedelta
from typing import List, Tuple

import httpx

# Configuration
API_URL = "http://localhost:8000/metrics/heart-rate"
BATCH_API_URL = "http://localhost:8000/metrics/heart-rate/batch"
TOTAL_READINGS = 10_000
DURATION_SECONDS = 120  # ~2 minutes (not used in fast mode)
USER_ID = "user_123"
DEVICES = ["device_a", "device_b", "device_c"]  # Multiple devices
DEVICE_WEIGHTS = [0.4, 0.4, 0.2]  # device_a and device_b more common
BATCH_SIZE = 50  # Readings per batch request (reduced for testing)
TEST_MODE = False  # Set to True for testing with only 10 batches
MAX_BATCHES_FOR_TEST = 10  # Limit batches when in test mode

# Heart rate ranges (realistic values)
HEART_RATE_RANGES = {
    "device_a": (60, 100),  # Medical grade - more accurate
    "device_b": (55, 105),  # Consumer wearable - wider range
    "device_c": (50, 110),  # Basic device - widest range
}

# Burst patterns: (start_time_offset, duration, multiplier)
BURST_PATTERNS = [
    (10, 5, 3.0),   # Burst at 10s, lasts 5s, 3x normal rate
    (45, 3, 5.0),   # Burst at 45s, lasts 3s, 5x normal rate
    (90, 10, 2.0),  # Burst at 90s, lasts 10s, 2x normal rate
]


async def send_batch(
    client: httpx.AsyncClient,
    batch_data: bytes,
) -> Tuple[bool, int, int]:
    """Send a batch of heart rate readings to the API."""
    try:
        # Parse JSON from bytes
        batch_json = json.loads(batch_data.decode('utf-8'))
        response = await client.post(
            BATCH_API_URL,
            json=batch_json,
            timeout=30.0,
        )
        if response.status_code == 202:
            result = response.json()
            return True, result.get("accepted", 0), result.get("rejected", 0)
        else:
            # Log first error to see what's wrong
            print(f"\n[DEBUG] Status {response.status_code}: {response.text[:200]}")
            return False, 0, 0
    except json.JSONDecodeError as e:
        print(f"\n[DEBUG] JSON decode error: {e}")
        return False, 0, 0
    except httpx.ReadTimeout:
        # Timeout - server taking too long
        print("\n[DEBUG] ReadTimeout: Server took longer than 30s to respond")
        return False, 0, 0
    except Exception as e:
        # Log first exception to see what's wrong
        print(f"\n[DEBUG] Exception: {type(e).__name__}: {str(e)[:200]}")
        return False, 0, 0


def generate_timestamps(
    start_time: datetime, total_readings: int, duration: int
) -> List[datetime]:
    """Generate timestamps with some out-of-order entries."""
    timestamps = []
    base_interval = duration / total_readings

    for i in range(total_readings):
        # Base timestamp
        base_offset = i * base_interval

        # Add some randomness for realistic distribution
        jitter = random.uniform(-0.5, 0.5) * base_interval
        timestamp = start_time + timedelta(seconds=base_offset + jitter)

        timestamps.append(timestamp)

    # Introduce out-of-order timestamps (5% of readings)
    out_of_order_count = int(total_readings * 0.05)
    for _ in range(out_of_order_count):
        idx1 = random.randint(0, total_readings - 1)
        idx2 = random.randint(0, total_readings - 1)
        timestamps[idx1], timestamps[idx2] = timestamps[idx2], timestamps[idx1]

    return timestamps


def get_burst_multiplier(elapsed_time: float) -> float:
    """Get the current burst multiplier based on elapsed time."""
    for burst_start, burst_duration, multiplier in BURST_PATTERNS:
        if burst_start <= elapsed_time < burst_start + burst_duration:
            return multiplier
    return 1.0


async def generate_and_send_data() -> None:
    """Main function to generate and send test data."""
    start_time = datetime(2024, 1, 15, 10, 0, 0)
    end_time = start_time + timedelta(seconds=DURATION_SECONDS)

    # Generate all timestamps upfront
    timestamps = generate_timestamps(start_time, TOTAL_READINGS, DURATION_SECONDS)
    timestamps.sort()  # Sort for realistic progression

    # Calculate send times (spread over duration)
    send_times = []
    for i, ts in enumerate(timestamps):
        elapsed = (ts - start_time).total_seconds()
        send_times.append((elapsed, ts))

    # Add some duplicates (2% of readings)
    duplicate_count = int(TOTAL_READINGS * 0.02)
    for _ in range(duplicate_count):
        idx = random.randint(0, len(send_times) - 1)
        send_times.append(send_times[idx])  # Exact duplicate

    # Shuffle to simulate concurrent sending
    random.shuffle(send_times)

    print(f"Generating {len(send_times)} heart rate readings...")
    print(f"Time range: {start_time.isoformat()}Z to {end_time.isoformat()}Z")
    print(f"Devices: {', '.join(DEVICES)}")
    print(f"Burst patterns: {len(BURST_PATTERNS)}")
    print("-" * 60)

    # Optimize httpx client for high throughput
    limits = httpx.Limits(max_keepalive_connections=200, max_connections=500)
    timeout = httpx.Timeout(10.0, connect=2.0)

    # Try HTTP/2 if available, fallback to HTTP/1.1
    # HTTP/2 requires httpx[http2] extra (h2 package)
    client_kwargs = {"limits": limits, "timeout": timeout}
    # Check if h2 package is available
    if importlib.util.find_spec("h2") is not None:
        client_kwargs["http2"] = True

    async with httpx.AsyncClient(**client_kwargs) as client:
        # Check API is available
        try:
            health_response = await client.get("http://localhost:8000/health", timeout=2.0)
            if health_response.status_code != 200:
                print("ERROR: API health check failed!")
                return
        except Exception:
            print("ERROR: Cannot connect to API at http://localhost:8000")
            print("Make sure the server is running: uv run uvicorn core.main:app --reload")
            return

        print("API is ready. Starting optimized batch data generation...\n")
        print(f"Total readings to send: {len(send_times)}")
        print(f"Batch size: {BATCH_SIZE} readings per request")
        print(f"Expected batches: {(len(send_times) + BATCH_SIZE - 1) // BATCH_SIZE}\n")

        # Start timing
        total_start_time = time.time()
        generation_start_time = time.time()

        # Generate all readings data
        print("1 - Generating reading data...", flush=True)
        all_readings = []
        for elapsed, timestamp in send_times:
            # Determine burst multiplier (for data generation, not timing)
            burst_mult = get_burst_multiplier(elapsed)
            requests_now = max(1, int(burst_mult))

            for _ in range(requests_now):
                # Select device (weighted random)
                device_id = random.choices(DEVICES, weights=DEVICE_WEIGHTS)[0]

                # Generate heart rate within device's range
                min_hr, max_hr = HEART_RATE_RANGES[device_id]
                heart_rate = random.randint(min_hr, max_hr)

                # Add some variation for duplicates
                if random.random() < 0.1:  # 10% chance of slight variation
                    heart_rate += random.randint(-2, 2)
                    heart_rate = max(30, min(220, heart_rate))  # Clamp to valid range

                all_readings.append({
                    "device_id": device_id,
                    "user_id": USER_ID,
                    "timestamp": timestamp.isoformat() + "Z",
                    "heart_rate": heart_rate,
                })

        generation_time = time.time() - generation_start_time
        print(f"\r1 - Generated {len(all_readings)} readings in {generation_time:.2f}s")

        # Pre-serialize batches
        print("2 - Pre-serializing batches...", flush=True)
        serialization_start_time = time.time()
        batches = []
        batch_json_strings = []

        for i in range(0, len(all_readings), BATCH_SIZE):
            batch_readings = all_readings[i:i + BATCH_SIZE]
            batch_payload = {"readings": batch_readings}
            # Pre-serialize JSON
            json_str = json.dumps(batch_payload)
            batch_json_strings.append(json_str.encode('utf-8'))
            batches.append(batch_readings)

            # Limit batches in test mode
            if TEST_MODE and len(batches) >= MAX_BATCHES_FOR_TEST:
                print(f"\n[TEST MODE] Limiting to {MAX_BATCHES_FOR_TEST} batches")
                break

        serialization_time = time.time() - serialization_start_time
        print(f"\r2 - Pre-serialized {len(batches)} batches in {serialization_time:.2f}s")

        # Send batches concurrently
        print("3 - Sending batches...", flush=True)
        send_start_time = time.time()

        # Allow 10 concurrent batch requests (reduced to avoid overwhelming server)
        semaphore = asyncio.Semaphore(10)
        total_accepted = 0
        total_rejected = 0
        error_count = 0
        completed_batches = 0

        error_details = []  # Store first few errors for debugging

        async def send_batch_with_semaphore(batch_data: bytes, batch_num: int) -> None:
            """Send batch with semaphore control."""
            nonlocal total_accepted, total_rejected, error_count, completed_batches, error_details
            async with semaphore:
                success, accepted, rejected = await send_batch(client, batch_data)
                if success:
                    total_accepted += accepted
                    total_rejected += rejected
                else:
                    error_count += 1
                    # Store first 3 errors for debugging
                    if len(error_details) < 3:
                        error_details.append(f"Batch {batch_num + 1} failed")
                completed_batches += 1
                # Print progress indicator
                if completed_batches % 5 == 0 or completed_batches == len(batches):
                    progress_pct = (completed_batches / len(batches)) * 100
                    elapsed = time.time() - send_start_time
                    rate = completed_batches / elapsed if elapsed > 0 else 0
                    print(f"\r3 - Sending batches... [{completed_batches}/{len(batches)}] "
                          f"{progress_pct:.1f}% | {rate:.1f} batches/s | "
                          f"Accepted: {total_accepted} | Rejected: {total_rejected} | "
                          f"Errors: {error_count}", end="", flush=True)

        # Create and start all batch tasks
        tasks = [
            asyncio.create_task(send_batch_with_semaphore(batch_data, i))
            for i, batch_data in enumerate(batch_json_strings)
        ]

        # Wait for all batches to complete
        await asyncio.gather(*tasks, return_exceptions=True)

        send_time = time.time() - send_start_time
        print()  # New line

        # Print error details if any
        if error_details:
            print(f"\nFirst few errors: {error_details}")

        # Final timing and statistics
        total_time = time.time() - total_start_time

        print("\n" + "=" * 70)
        print("DATA GENERATION COMPLETE - PERFORMANCE METRICS")
        print("=" * 70)
        print(f"Total readings generated: {len(all_readings)}")
        print(f"Total batches sent: {len(batches)}")
        print(f"Readings accepted: {total_accepted}")
        print(f"Readings rejected: {total_rejected}")
        print(f"Batch errors: {error_count}")
        print(f"Success rate: {((total_accepted / len(all_readings)) * 100):.2f}%")
        print()
        print("TIMING BREAKDOWN:")
        print(f"  Data generation: {generation_time:.3f}s")
        print(f"  JSON serialization: {serialization_time:.3f}s")
        print(f"  Network sending: {send_time:.3f}s")
        print(f"  Total time: {total_time:.3f}s")
        print()
        print("PERFORMANCE METRICS:")
        print(f"  Readings/second: {len(all_readings) / total_time:.2f}")
        print(f"  Batches/second: {len(batches) / send_time:.2f}")
        print(f"  Readings/batch: {BATCH_SIZE}")
        print(f"  Speed improvement: ~{120 / total_time:.1f}x faster than original 2-minute target")
        print("=" * 70)
        print("\nYou can now query the data:")
        print(f'curl "http://localhost:8000/metrics/heart-rate?user_id={USER_ID}&start={start_time.isoformat()}Z&end={end_time.isoformat()}Z"')


if __name__ == "__main__":
    print("Heart Rate Metrics Data Generator")
    print("=" * 60)
    asyncio.run(generate_and_send_data())

