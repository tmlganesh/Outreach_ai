"""
Data export utilities.

Provides CSV and JSON export for pipeline results.
Exports are timestamped and stored in the exports/ directory.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.config.settings import get_settings
from app.models.schemas import PipelineResult


def _timestamp() -> str:
    """Generate a file-safe timestamp."""
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S")


def export_csv(result: PipelineResult, output_dir: Optional[Path] = None) -> Path:
    """
    Export pipeline results to CSV.

    Creates separate CSV files for companies, contacts, emails,
    and messages, plus a combined summary.
    """
    settings = get_settings()
    export_dir = output_dir or settings.exports_dir
    export_dir.mkdir(parents=True, exist_ok=True)
    ts = _timestamp()
    run_dir = export_dir / f"run_{result.run_id}_{ts}"
    run_dir.mkdir(exist_ok=True)

    # Companies CSV
    if result.companies:
        path = run_dir / "companies.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["domain", "name", "industry", "size", "country"])
            writer.writeheader()
            for c in result.companies:
                writer.writerow({
                    "domain": c.domain,
                    "name": c.name,
                    "industry": c.industry,
                    "size": c.size,
                    "country": c.country,
                })

    # Contacts CSV
    if result.contacts:
        path = run_dir / "contacts.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "full_name", "title", "seniority", "company_name", "company_domain", "linkedin_url",
            ])
            writer.writeheader()
            for c in result.contacts:
                writer.writerow({
                    "full_name": c.display_name,
                    "title": c.title,
                    "seniority": c.seniority,
                    "company_name": c.company_name,
                    "company_domain": c.company_domain,
                    "linkedin_url": c.linkedin_url,
                })

    # Emails CSV
    if result.emails:
        path = run_dir / "emails.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "email", "contact_name", "contact_title", "company_name", "company_domain",
                "verification_status", "source",
            ])
            writer.writeheader()
            for e in result.emails:
                writer.writerow({
                    "email": e.email,
                    "contact_name": e.contact_name,
                    "contact_title": e.contact_title,
                    "company_name": e.company_name,
                    "company_domain": e.company_domain,
                    "verification_status": e.verification_status,
                    "source": e.source,
                })

    # Messages CSV
    if result.messages:
        path = run_dir / "messages.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "to_email", "to_name", "company_name", "subject", "status", "sent_at",
            ])
            writer.writeheader()
            for m in result.messages:
                writer.writerow({
                    "to_email": m.to_email,
                    "to_name": m.to_name,
                    "company_name": m.company_name,
                    "subject": m.subject,
                    "status": m.status,
                    "sent_at": str(m.sent_at) if m.sent_at else "",
                })

    # Failed contacts
    if result.failed_contacts:
        path = run_dir / "failed_contacts.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["name", "title", "company", "domain", "reason"])
            writer.writeheader()
            for fc in result.failed_contacts:
                writer.writerow(fc)

    return run_dir


def export_json(result: PipelineResult, output_dir: Optional[Path] = None) -> Path:
    """Export the full pipeline result as a JSON file."""
    settings = get_settings()
    export_dir = output_dir or settings.exports_dir
    export_dir.mkdir(parents=True, exist_ok=True)
    ts = _timestamp()

    path = export_dir / f"run_{result.run_id}_{ts}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result.model_dump(mode="json"), f, indent=2, default=str)

    return path


def save_run_history(result: PipelineResult) -> Path:
    """Append a lightweight run record to the history file."""
    settings = get_settings()
    history_path = settings.data_dir / "run_history.json"

    # Load existing history
    history: list[dict] = []
    if history_path.exists():
        with open(history_path, "r", encoding="utf-8") as f:
            try:
                history = json.load(f)
            except json.JSONDecodeError:
                history = []

    # Append new record
    record = {
        "run_id": result.run_id,
        "seed_domain": result.seed_domain,
        "started_at": str(result.started_at),
        "completed_at": str(result.completed_at) if result.completed_at else None,
        "total_companies": result.total_companies,
        "total_contacts": result.total_contacts,
        "total_emails": result.total_emails,
        "total_sent": result.total_sent,
        "total_failed": result.total_failed,
        "dry_run": result.dry_run,
        "status": "completed",
    }
    history.append(record)

    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, default=str)

    return history_path


def load_run_history() -> list[dict]:
    """Load the run history from disk."""
    settings = get_settings()
    history_path = settings.data_dir / "run_history.json"

    if not history_path.exists():
        return []

    with open(history_path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []
