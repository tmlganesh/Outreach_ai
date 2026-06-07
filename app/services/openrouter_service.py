"""
OpenRouter API Integration — LLM Email Generation.

Calls OpenRouter to generate highly personalized outreach emails.
"""

from __future__ import annotations

import json
from typing import Any

from app.services.base import BaseService, APIError

class OpenRouterService(BaseService):
    """Generate personalized outreach emails via OpenRouter LLMs."""

    SERVICE_NAME = "openrouter"

    def __init__(self) -> None:
        super().__init__()
        self.BASE_URL = self.settings.openrouter_base_url

    def _default_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.settings.openrouter_api_key}",
            "HTTP-Referer": "https://outreachpilot.com",
            "X-Title": "OutreachPilot",
        }

    async def generate_email(
        self,
        prompt: str,
        model: str = "openai/gpt-4o-mini",
        system_prompt: str = "You are an expert B2B sales copywriter.",
    ) -> dict[str, str]:
        """
        Generate an email subject and body.
        Expects the LLM to return JSON with 'subject', 'body_html', and 'body_text'.
        """
        payload = {
            "model": model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
        }

        data = await self._request("POST", "/chat/completions", json=payload)
        try:
            content = data["choices"][0]["message"]["content"]
            result = json.loads(content)
            return {
                "subject": result.get("subject", "Quick question"),
                "body_html": result.get("body_html", "<p>Hi</p>"),
                "body_text": result.get("body_text", "Hi"),
            }
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            self.logger.error("openrouter_parse_error", error=str(e), response=data)
            raise APIError(self.SERVICE_NAME, f"Invalid response format: {str(e)}")
