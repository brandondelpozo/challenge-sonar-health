"""Main FastAPI application for heart rate metrics ingestion system."""

from fastapi import FastAPI

from core.api import lifespan, router

app = FastAPI(
    title="Heart Rate Metrics API",
    description="FastAPI service for ingesting and querying heart rate data from multiple devices",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router)

