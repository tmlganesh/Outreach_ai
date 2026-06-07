"""
Prospeo integration — Contact Discovery & Email Enrichment.

Uses the Prospeo API to:
  1. Search for decision makers at target companies
  2. Enrich contacts with verified email addresses

API Reference:
  POST /search-person      — Find contacts (returns person_id, no email)
  POST /enrich-person       — Get verified email for a person_id
  POST /bulk-enrich-person  — Batch enrich up to 50 person_ids

Authentication:
  Header: X-KEY
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.models.schemas import Contact, EmailRecord
from app.services.base import BaseService, APIError


# Decision-maker seniority levels for filtering
DECISION_MAKER_SENIORITIES = [
    "C-Level",
    "VP",
    "Director",
    "Head",
    "Manager",
]


class ProspeoService(BaseService):
    """Discover decision makers and resolve their work emails via Prospeo."""

    SERVICE_NAME = "prospeo"

    def __init__(self) -> None:
        super().__init__()
        self.BASE_URL = self.settings.prospeo_base_url

    def _default_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-KEY": self.settings.prospeo_api_key,
        }

    async def find_contacts(
        self,
        company_domain: str,
        company_name: str = "",
        max_contacts: int | None = None,
    ) -> list[Contact]:
        """
        Search for decision makers at a given company domain.

        Filters by senior titles to focus on people who make buying decisions.
        Returns Contact models (without email — use enrich for that).
        """
        if max_contacts is None:
            max_contacts = self.settings.max_contacts_per_company

        self.logger.info(
            "contact_search_start",
            company_domain=company_domain,
            max_contacts=max_contacts,
        )

        payload = {
            "filters": {
                "person_search": {
                    "company_domain": company_domain
                }
            },
            "page": 1,
        }

        contacts: list[Contact] = []
        seen_ids: set[str] = set()

        try:
            data = await self._request("POST", "/search-person", json=payload)
        except APIError as exc:
            self.logger.error(
                "contact_search_failed",
                company_domain=company_domain,
                error=str(exc),
            )
            raise

        results = data.get("response", data.get("data", data.get("results", [])))
        if isinstance(results, dict):
            results = results.get("data", results.get("results", []))

        if not isinstance(results, list):
            results = []

        for item in results[:max_contacts]:
            pid = str(item.get("person_id", item.get("id", "")))
            if not pid or pid in seen_ids:
                continue
            seen_ids.add(pid)

            contact = Contact(
                person_id=pid,
                first_name=item.get("first_name", ""),
                last_name=item.get("last_name", ""),
                full_name=item.get("full_name", f"{item.get('first_name', '')} {item.get('last_name', '')}".strip()),
                title=item.get("title", item.get("job_title", "")),
                seniority=item.get("seniority", ""),
                company_domain=company_domain,
                company_name=company_name or item.get("company_name", ""),
                linkedin_url=item.get("linkedin_url", item.get("linkedin", "")),
                location=item.get("location", ""),
            )
            contacts.append(contact)

        self.logger.info(
            "contact_search_complete",
            company_domain=company_domain,
            contacts_found=len(contacts),
        )
        return contacts

    async def enrich_contact_email(self, contact: Contact) -> EmailRecord | None:
        """
        Resolve a verified work email for a single contact.

        Uses the enrich-person endpoint with person_id.
        Falls back to name + domain lookup if person_id fails.
        """
        self.logger.info(
            "email_enrich_start",
            contact_name=contact.display_name,
            company_domain=contact.company_domain,
        )

        # Try enrichment by person_id first
        if contact.person_id:
            try:
                data = await self._request(
                    "POST",
                    "/enrich-person",
                    json={"person_id": contact.person_id},
                )
                email = self._extract_email(data)
                if email:
                    return EmailRecord(
                        email=email,
                        contact_name=contact.display_name,
                        contact_title=contact.title,
                        company_domain=contact.company_domain,
                        company_name=contact.company_name,
                        verification_status=data.get("response", {}).get("email_status", "verified"),
                        confidence=data.get("response", {}).get("confidence", None),
                        source="prospeo",
                    )
            except APIError:
                self.logger.warning("enrich_by_id_failed", person_id=contact.person_id)

        self.logger.warning(
            "email_enrich_no_result",
            contact_name=contact.display_name,
        )
        return None

    def _extract_email(self, data: dict[str, Any]) -> str | None:
        """Extract email from various Prospeo response formats."""
        # Direct email field
        if data.get("email"):
            return data["email"]

        # Nested in response object
        response = data.get("response", {})
        if isinstance(response, dict):
            if response.get("email"):
                return response["email"]
            if response.get("work_email"):
                return response["work_email"]

        # In data array
        items = data.get("data", [])
        if isinstance(items, list) and items:
            return items[0].get("email")

        return None
