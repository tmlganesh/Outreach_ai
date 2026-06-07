"""
Eazyreach integration — Email Verification & Resolution.

Acts as a secondary email resolution source. Verifies emails
discovered by Prospeo and attempts to resolve emails that
Prospeo couldn't find.

Note: Eazyreach's public API documentation is limited.
This implementation uses a standard REST pattern with
Bearer token authentication based on the provided credentials.

Authentication:
  Header: Authorization: Bearer <token>
  Header: X-API-Key: <api_key>
"""

from __future__ import annotations

from app.models.schemas import Contact, EmailRecord
from app.services.base import BaseService, APIError


class EazyreachService(BaseService):
    """Verify and resolve work emails through Eazyreach."""

    SERVICE_NAME = "eazyreach"

    def __init__(self) -> None:
        super().__init__()
        self.BASE_URL = self.settings.eazyreach_base_url

    def _default_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self.settings.eazyreach_token}",
            "X-API-Key": self.settings.eazyreach_api_key,
        }

    async def find_email(self, contact: Contact) -> EmailRecord | None:
        """
        Attempt to find a verified work email for a contact.

        Sends the contact's name and company domain to Eazyreach's
        email finder endpoint.
        """
        if not contact.first_name or not contact.company_domain:
            self.logger.warning(
                "insufficient_data",
                contact_name=contact.display_name,
            )
            return None

        self.logger.info(
            "email_find_start",
            contact_name=contact.display_name,
            company_domain=contact.company_domain,
        )

        payload = {
            "first_name": contact.first_name,
            "last_name": contact.last_name,
            "domain": contact.company_domain,
            "company": contact.company_name,
        }

        try:
            data = await self._request("POST", "/email/find", json=payload)
        except APIError as exc:
            self.logger.warning(
                "email_find_failed",
                contact_name=contact.display_name,
                error=str(exc),
            )
            return None

        email = data.get("email", data.get("data", {}).get("email"))
        if not email:
            return None

        return EmailRecord(
            email=email,
            contact_name=contact.display_name,
            contact_title=contact.title,
            company_domain=contact.company_domain,
            company_name=contact.company_name,
            verification_status=data.get("status", data.get("verification", "verified")),
            confidence=data.get("confidence", data.get("score")),
            source="eazyreach",
        )

    async def verify_email(self, email: str) -> dict:
        """
        Verify an existing email address.

        Returns verification result with status and deliverability info.
        """
        self.logger.info("email_verify_start", email=email)

        try:
            data = await self._request(
                "POST",
                "/email/verify",
                json={"email": email},
            )
            self.logger.info(
                "email_verify_complete",
                email=email,
                status=data.get("status", "unknown"),
            )
            return data
        except APIError as exc:
            self.logger.warning(
                "email_verify_failed",
                email=email,
                error=str(exc),
            )
            return {"status": "unknown", "error": str(exc)}
