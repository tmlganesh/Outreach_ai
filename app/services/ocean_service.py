"""
Ocean.io integration — Company Lookalike Search.

Uses the Ocean.io v3 API to find companies similar to a seed domain.
The lookalike search leverages Ocean's proprietary vectoring model to
identify firmographic, technographic, and behavioral similarity.

API Reference:
  POST /search/companies
  Header: X-Api-Token
"""

from __future__ import annotations

from app.models.schemas import Company
from app.services.base import BaseService, APIError


class OceanService(BaseService):
    """Find companies similar to a given seed domain using Ocean.io."""

    SERVICE_NAME = "ocean"

    def __init__(self) -> None:
        super().__init__()
        self.BASE_URL = self.settings.ocean_base_url

    def _default_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Api-Token": self.settings.ocean_api_key,
        }

    async def find_similar_companies(
        self,
        seed_domain: str,
        max_results: int | None = None,
    ) -> list[Company]:
        """
        Search for companies similar to the seed domain.

        Steps:
          1. Preview query to get total count (costs 0 credits)
          2. Fetch actual results up to max_results

        Returns a deduplicated list of Company models.
        """
        if max_results is None:
            max_results = self.settings.max_companies

        self.logger.info("lookalike_search_start", seed_domain=seed_domain, max_results=max_results)

        # Build the search payload
        payload = {
            "size": min(max_results, 100),
            "fields": [
                "domain", "name", "companySize", "primaryCountry",
                "industries", "description",
            ],
            "companiesFilters": {
                "lookalikeDomains": [seed_domain],
            },
        }

        companies: list[Company] = []
        seen_domains: set[str] = set()
        search_after: str | None = None

        while len(companies) < max_results:
            if search_after:
                payload["searchAfter"] = search_after

            try:
                data = await self._request("POST", "/search/companies", json=payload)
            except APIError as exc:
                self.logger.error("lookalike_search_failed", error=str(exc))
                raise

            results = data.get("companies", data.get("results", data.get("data", [])))
            if not results:
                break

            for item in results:
                company_data = item.get("company", {})
                domain = company_data.get("domain", "")
                if not domain or domain in seen_domains:
                    continue
                seen_domains.add(domain)

                company = Company(
                    domain=domain,
                    name=company_data.get("name", ""),
                    industry=", ".join(company_data.get("industries", [])) if isinstance(company_data.get("industries"), list) else company_data.get("industries", ""),
                    size=str(company_data.get("companySize", "")),
                    country=company_data.get("primaryCountry", ""),
                    description=company_data.get("description", "")[:200],
                    source_domain=seed_domain,
                )
                companies.append(company)

                if len(companies) >= max_results:
                    break

            # Pagination
            search_after = data.get("searchAfter")
            if not search_after:
                break

        self.logger.info(
            "lookalike_search_complete",
            seed_domain=seed_domain,
            companies_found=len(companies),
        )
        return companies
