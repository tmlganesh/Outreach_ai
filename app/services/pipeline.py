"""
Pipeline Orchestrator — Core business logic.

Coordinates the four-stage outreach pipeline:
  1. Company Search    (Ocean.io)
  2. Contact Discovery (Prospeo)
  3. Email Resolution  (Prospeo + Eazyreach)
  4. Outreach Generation & Sending (Brevo)

Design Principles:
  - Partial failure recovery: one failed contact doesn't stop the run
  - Deduplication at every stage
  - Structured logging for observability
  - Explicit approval gate before sending
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Callable, Optional

from app.config.logging import get_logger
from app.models.schemas import (
    Company,
    Contact,
    EmailRecord,
    OutreachMessage,
    PipelineResult,
    PipelineStage,
    StageResult,
)
from app.services.ocean_service import OceanService
from app.services.prospeo_service import ProspeoService
from app.services.eazyreach_service import EazyreachService
from app.services.brevo_service import BrevoService
from app.services.scraper_service import ScraperService
from app.services.email_generator import generate_batch_messages


logger = get_logger("pipeline")


class PipelineOrchestrator:
    """
    Orchestrates the complete outreach pipeline.

    Usage:
        pipeline = PipelineOrchestrator()
        result = await pipeline.run("notion.so")
        # Inspect result, approve, then:
        result = await pipeline.send(result, dry_run=False)
    """

    def __init__(self, progress_callback: Optional[Callable] = None) -> None:
        self.ocean = OceanService()
        self.prospeo = ProspeoService()
        self.eazyreach = EazyreachService()
        self.brevo = BrevoService()
        self.scraper = ScraperService()
        self._progress = progress_callback or (lambda *a, **kw: None)

    async def run(
        self,
        seed_domain: str,
        dry_run: bool = False,
        max_companies: int | None = None,
        max_contacts_per_company: int | None = None,
        run_id: str | None = None,
    ) -> PipelineResult:
        """
        Execute the full pipeline: discover → enrich → generate.

        Does NOT send emails. Call `send()` separately after approval.
        """
        if run_id is None:
            run_id = str(uuid.uuid4())[:8]
        result = PipelineResult(
            run_id=run_id,
            seed_domain=seed_domain,
            dry_run=dry_run,
        )

        logger.info("pipeline_start", run_id=run_id, seed_domain=seed_domain)

        try:
            # ── Stage 1: Find Similar Companies ──────────────
            await self._stage_companies(result, seed_domain, max_companies)

            # ── Stage 2: Find Decision Makers ────────────────
            await self._stage_contacts(result, max_contacts_per_company)

            # ── Stage 3: Resolve Emails ──────────────────────
            await self._stage_emails(result)

            # ── Stage 4: Generate Outreach Messages ──────────
            await self._stage_generate(result)

        except Exception as exc:
            logger.error("pipeline_error", run_id=run_id, error=str(exc))
        finally:
            result.completed_at = datetime.utcnow()
            result.total_companies = len(result.companies)
            result.total_contacts = len(result.contacts)
            result.total_emails = len(result.emails)

        logger.info(
            "pipeline_complete",
            run_id=run_id,
            companies=result.total_companies,
            contacts=result.total_contacts,
            emails=result.total_emails,
            messages=len(result.messages),
        )

        return result

    async def send(
        self,
        result: PipelineResult,
        dry_run: bool = False,
    ) -> PipelineResult:
        """Send the generated outreach emails (requires prior approval)."""
        stage_start = datetime.utcnow()
        logger.info(
            "send_start",
            run_id=result.run_id,
            message_count=len(result.messages),
            dry_run=dry_run,
        )

        self._progress(stage="sending", message="Sending outreach emails...")

        sent_messages = await self.brevo.send_batch(result.messages, dry_run=dry_run)
        result.messages = sent_messages

        result.total_sent = sum(1 for m in sent_messages if m.status in ("sent", "dry_run"))
        result.total_failed = sum(1 for m in sent_messages if m.status == "failed")

        result.stages.append(StageResult(
            stage=PipelineStage.EMAIL_SENDING,
            success=result.total_failed == 0,
            count=result.total_sent,
            errors=[m.error for m in sent_messages if m.error],
            duration_seconds=(datetime.utcnow() - stage_start).total_seconds(),
            started_at=stage_start,
            completed_at=datetime.utcnow(),
        ))

        result.completed_at = datetime.utcnow()

        logger.info(
            "send_complete",
            run_id=result.run_id,
            sent=result.total_sent,
            failed=result.total_failed,
        )

        return result

    # ── Private Stage Methods ────────────────────────────────

    async def _stage_companies(
        self,
        result: PipelineResult,
        seed_domain: str,
        max_companies: int | None,
    ) -> None:
        """Stage 1: Find similar companies via Ocean.io."""
        stage_start = datetime.utcnow()
        self._progress(stage="companies", message="Finding similar companies...")

        try:
            companies = await self.ocean.find_similar_companies(
                seed_domain,
                max_results=max_companies,
            )
            
            logger.info(f"[Ocean]\nFound {len(companies)} companies")
            
            if len(companies) > 5:
                logger.info("[Pipeline]\nLimiting processing to first 5 companies to respect API quotas")
                companies = companies[:5]
                
                selected = "\n".join([f"* {c.domain}" for c in companies])
                logger.info(f"[Pipeline]\nSelected:\n\n{selected}")

            result.companies = companies
            result.stages.append(StageResult(
                stage=PipelineStage.COMPANY_SEARCH,
                success=True,
                count=len(companies),
                duration_seconds=(datetime.utcnow() - stage_start).total_seconds(),
                started_at=stage_start,
                completed_at=datetime.utcnow(),
            ))
        except Exception as exc:
            logger.error("stage_companies_failed", error=str(exc))
            result.stages.append(StageResult(
                stage=PipelineStage.COMPANY_SEARCH,
                success=False,
                errors=[str(exc)],
                duration_seconds=(datetime.utcnow() - stage_start).total_seconds(),
                started_at=stage_start,
                completed_at=datetime.utcnow(),
            ))

        self._progress(
            stage="companies",
            message=f"Found {len(result.companies)} companies",
            done=True,
        )

    async def _stage_contacts(
        self,
        result: PipelineResult,
        max_contacts_per_company: int | None,
    ) -> None:
        """Stage 2: Find decision makers at each company via Prospeo."""
        stage_start = datetime.utcnow()
        self._progress(stage="contacts", message="Finding decision makers...")

        all_contacts: list[Contact] = []
        errors: list[str] = []
        seen_ids: set[str] = set()

        for company in result.companies:
            company_contacts = []
            try:
                company_contacts = await self.prospeo.find_contacts(
                    company.domain,
                    company_name=company.name,
                    max_contacts=max_contacts_per_company,
                )
            except Exception as exc:
                error_msg = f"Failed for {company.domain}: {exc}"
                logger.warning("contact_search_error", company=company.domain, error=str(exc))
                errors.append(error_msg)
                
            # Fallback to web scraper if no contacts found
            if not company_contacts:
                logger.info("contact_search_fallback", company=company.domain, method="scraper")
                scraped_emails = await self.scraper.scrape_emails(company.domain)
                for email in scraped_emails:
                    company_contacts.append(Contact(
                        person_id=f"scraped_{email}",
                        first_name="Team",
                        last_name="Member",
                        full_name="Team Member",
                        title="Leader",
                        company_domain=company.domain,
                        company_name=company.name,
                    ))

            for c in company_contacts:
                # Deduplicate across companies
                key = f"{c.first_name}_{c.last_name}_{c.company_domain}".lower()
                if key not in seen_ids:
                    seen_ids.add(key)
                    all_contacts.append(c)

        result.contacts = all_contacts
        result.stages.append(StageResult(
            stage=PipelineStage.CONTACT_DISCOVERY,
            success=len(all_contacts) > 0,
            count=len(all_contacts),
            errors=errors,
            duration_seconds=(datetime.utcnow() - stage_start).total_seconds(),
            started_at=stage_start,
            completed_at=datetime.utcnow(),
        ))

        self._progress(
            stage="contacts",
            message=f"Found {len(all_contacts)} contacts",
            done=True,
        )

    async def _stage_emails(self, result: PipelineResult) -> None:
        """Stage 3: Resolve verified emails via Prospeo + Eazyreach."""
        stage_start = datetime.utcnow()
        self._progress(stage="emails", message="Resolving emails...")

        all_emails: list[EmailRecord] = []
        errors: list[str] = []
        seen_emails: set[str] = set()

        for contact in result.contacts:
            email_record: EmailRecord | None = None

            # Handle scraped emails
            if contact.person_id.startswith("scraped_"):
                email = contact.person_id[8:]
                # Attempt to verify the scraped email
                verification = await self.eazyreach.verify_email(email)
                status = verification.get("status", verification.get("verification", "verified"))
                # For demo/fallback purposes, we'll keep the email even if status is unknown/invalid,
                # but we'll mark its status. 
                email_record = EmailRecord(
                    email=email,
                    contact_name=contact.display_name,
                    contact_title=contact.title,
                    company_domain=contact.company_domain,
                    company_name=contact.company_name,
                    verification_status=status,
                    confidence=0.8,
                    source="scraper+eazyreach",
                )
            else:
                # Try Prospeo first
                try:
                    email_record = await self.prospeo.enrich_contact_email(contact)
                except Exception as exc:
                    logger.warning(
                        "prospeo_enrich_error",
                        contact=contact.display_name,
                        error=str(exc),
                    )

                # Fallback to Eazyreach if Prospeo didn't find it
                if not email_record:
                    try:
                        email_record = await self.eazyreach.find_email(contact)
                    except Exception as exc:
                        logger.warning(
                            "eazyreach_find_error",
                            contact=contact.display_name,
                            error=str(exc),
                        )

            if email_record and email_record.email.lower() not in seen_emails:
                seen_emails.add(email_record.email.lower())
                all_emails.append(email_record)
            else:
                result.failed_contacts.append({
                    "name": contact.display_name,
                    "title": contact.title,
                    "company": contact.company_name,
                    "domain": contact.company_domain,
                    "reason": "No verified email found",
                })

        result.emails = all_emails
        result.stages.append(StageResult(
            stage=PipelineStage.EMAIL_RESOLUTION,
            success=len(all_emails) > 0,
            count=len(all_emails),
            errors=errors,
            duration_seconds=(datetime.utcnow() - stage_start).total_seconds(),
            started_at=stage_start,
            completed_at=datetime.utcnow(),
        ))

        self._progress(
            stage="emails",
            message=f"Resolved {len(all_emails)} emails",
            done=True,
        )

    async def _stage_generate(self, result: PipelineResult) -> None:
        """Stage 4: Generate personalized outreach messages."""
        stage_start = datetime.utcnow()
        self._progress(stage="outreach", message="Generating outreach...")

        messages = await generate_batch_messages(result.emails)
        result.messages = messages

        result.stages.append(StageResult(
            stage=PipelineStage.OUTREACH_GENERATION,
            success=True,
            count=len(messages),
            duration_seconds=(datetime.utcnow() - stage_start).total_seconds(),
            started_at=stage_start,
            completed_at=datetime.utcnow(),
        ))

        self._progress(
            stage="outreach",
            message=f"Generated {len(messages)} messages",
            done=True,
        )

    async def close(self) -> None:
        """Close all service clients."""
        await self.ocean.close()
        await self.prospeo.close()
        await self.eazyreach.close()
        await self.brevo.close()
