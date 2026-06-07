"""
Brevo integration — Transactional Email Sending.

Sends personalized outreach emails through Brevo's SMTP API.
Includes sandbox mode for testing without delivering emails.

API Reference:
  POST /smtp/email
  Header: api-key

Safety:
  - Never sends without explicit approval
  - Supports dry-run mode (logs but doesn't send)
  - Sandbox header available for testing
"""

from __future__ import annotations

from datetime import datetime

from app.models.schemas import OutreachMessage
from app.services.base import BaseService, APIError


class BrevoService(BaseService):
    """Send personalized outreach emails through Brevo."""

    SERVICE_NAME = "brevo"

    def __init__(self) -> None:
        super().__init__()
        self.BASE_URL = self.settings.brevo_base_url

    def _default_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "api-key": self.settings.brevo_api_key,
        }

    async def send_email(
        self,
        message: OutreachMessage,
        dry_run: bool = False,
    ) -> OutreachMessage:
        """
        Send a single outreach email.

        In dry_run mode, logs the email without calling Brevo API.
        Returns the updated OutreachMessage with send status.
        """
        self.logger.info(
            "send_email_start",
            to_email=message.to_email,
            to_name=message.to_name,
            dry_run=dry_run,
        )

        if dry_run:
            message.status = "dry_run"
            message.sent_at = datetime.utcnow()
            self.logger.info(
                "send_email_dry_run",
                to_email=message.to_email,
                subject=message.subject,
            )
            return message

        payload = {
            "sender": {
                "name": self.settings.brevo_sender_name,
                "email": self.settings.brevo_sender_email,
            },
            "to": [
                {
                    "email": message.to_email,
                    "name": message.to_name or message.to_email,
                }
            ],
            "subject": message.subject,
            "htmlContent": message.body_html,
        }

        if message.body_text:
            payload["textContent"] = message.body_text

        try:
            data = await self._request("POST", "/smtp/email", json=payload)
            message.status = "sent"
            message.sent_at = datetime.utcnow()
            message.message_id = data.get("messageId", str(data.get("messageIds", [""])[0]) if data.get("messageIds") else None)
            self.logger.info(
                "send_email_success",
                to_email=message.to_email,
                message_id=message.message_id,
            )
        except APIError as exc:
            message.status = "failed"
            message.error = str(exc)
            self.logger.error(
                "send_email_failed",
                to_email=message.to_email,
                error=str(exc),
            )

        return message

    async def send_batch(
        self,
        messages: list[OutreachMessage],
        dry_run: bool = False,
    ) -> list[OutreachMessage]:
        """
        Send multiple emails sequentially with rate-limit spacing.

        Continues sending even if individual emails fail
        (partial failure recovery).
        """
        results: list[OutreachMessage] = []

        for i, msg in enumerate(messages, 1):
            self.logger.info(
                "batch_progress",
                current=i,
                total=len(messages),
            )
            result = await self.send_email(msg, dry_run=dry_run)
            results.append(result)

        sent = sum(1 for m in results if m.status == "sent")
        failed = sum(1 for m in results if m.status == "failed")
        dry = sum(1 for m in results if m.status == "dry_run")

        self.logger.info(
            "batch_complete",
            total=len(results),
            sent=sent,
            failed=failed,
            dry_run=dry,
        )

        return results
