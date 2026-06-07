"""
REST API routes for programmatic pipeline access.

Provides JSON endpoints for integration with external tools.
The dashboard uses these for HTMX interactions.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.export import load_run_history


router = APIRouter(prefix="/api", tags=["api"])


class HealthResponse(BaseModel):
    status: str
    version: str


@router.get("/health", response_model=HealthResponse)
async def health():
    """Health check endpoint."""
    return HealthResponse(status="healthy", version="1.0.0")


@router.get("/history")
async def get_history():
    """Return run history as JSON."""
    return load_run_history()
