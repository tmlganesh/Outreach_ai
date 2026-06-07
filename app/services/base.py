"""
Base HTTP client with production-grade resilience.

Provides:
  - Automatic retries with exponential backoff
  - Timeout enforcement
  - Rate-limit detection and back-off
  - Structured logging for every request
  - Consistent error handling across all services
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

import httpx

from app.config.logging import get_logger
from app.config.settings import get_settings


class APIError(Exception):
    """Raised when an API call fails after all retries."""

    def __init__(self, service: str, message: str, status_code: int | None = None):
        self.service = service
        self.status_code = status_code
        super().__init__(f"[{service}] {message}")


class BaseService:
    """
    Abstract base for all external API integrations.

    Subclasses set `SERVICE_NAME` and `BASE_URL`, then call
    `self._request(method, path, **kwargs)` for resilient HTTP calls.

    Retry strategy:
      - Retry on 429 (rate limit), 500, 502, 503, 504
      - Exponential backoff: delay = backoff_factor ^ attempt
      - Honor Retry-After header when present
    """

    SERVICE_NAME: str = "base"
    BASE_URL: str = ""

    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

    def __init__(self) -> None:
        self.settings = get_settings()
        self.logger = get_logger(self.SERVICE_NAME)
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazy-initialize the async HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.BASE_URL,
                timeout=httpx.Timeout(self.settings.request_timeout),
                headers=self._default_headers(),
            )
        return self._client

    def _default_headers(self) -> dict[str, str]:
        """Override in subclasses to set auth headers."""
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict | None = None,
        headers: dict | None = None,
    ) -> dict[str, Any]:
        """
        Execute an HTTP request with retry logic.

        Returns the parsed JSON response body.
        Raises APIError on permanent failure.
        """
        client = await self._get_client()
        last_error: Exception | None = None

        for attempt in range(1, self.settings.max_retries + 1):
            try:
                self.logger.info(
                    "api_request",
                    method=method,
                    path=path,
                    attempt=attempt,
                    payload=str(json)[:1000] if json else None,
                )

                # Rate-limit spacing
                if attempt > 1:
                    backoff = self.settings.retry_backoff_factor ** (attempt - 1)
                    self.logger.info("retry_backoff", seconds=backoff, attempt=attempt)
                    await asyncio.sleep(backoff)
                else:
                    await asyncio.sleep(self.settings.rate_limit_delay)

                response = await client.request(
                    method,
                    path,
                    json=json,
                    params=params,
                    headers=headers,
                )

                # ── Rate-limit handling ──────────────────────
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    wait = float(retry_after) if retry_after else (self.settings.retry_backoff_factor ** attempt)
                    self.logger.warning(
                        "rate_limited",
                        retry_after=wait,
                        attempt=attempt,
                    )
                    await asyncio.sleep(wait)
                    continue

                # ── Server errors — retryable ────────────────
                if response.status_code in self.RETRYABLE_STATUS_CODES:
                    self.logger.warning(
                        "retryable_error",
                        status_code=response.status_code,
                        attempt=attempt,
                    )
                    continue

                # ── Client errors — not retryable ────────────
                if response.status_code >= 400:
                    error_body = response.text[:500]
                    self.logger.error(
                        "api_error",
                        status_code=response.status_code,
                        body=error_body,
                    )
                    raise APIError(
                        self.SERVICE_NAME,
                        f"HTTP {response.status_code}: {error_body}",
                        status_code=response.status_code,
                    )

                # ── Success ──────────────────────────────────
                data = response.json()
                self.logger.info(
                    "api_success",
                    status_code=response.status_code,
                    path=path,
                    response_body=str(data)[:1000]
                )
                return data

            except httpx.TimeoutException as exc:
                last_error = exc
                self.logger.warning(
                    "request_timeout",
                    attempt=attempt,
                    error=str(exc),
                )
            except httpx.RequestError as exc:
                last_error = exc
                self.logger.warning(
                    "request_error",
                    attempt=attempt,
                    error=str(exc),
                )
            except APIError:
                raise
            except Exception as exc:
                last_error = exc
                self.logger.error(
                    "unexpected_error",
                    attempt=attempt,
                    error=str(exc),
                )

        # All retries exhausted
        raise APIError(
            self.SERVICE_NAME,
            f"All {self.settings.max_retries} retries exhausted. Last error: {last_error}",
        )

    async def close(self) -> None:
        """Close the HTTP client cleanly."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
