"""
Unit tests for data models.

Validates Pydantic model creation, validation rules,
domain normalization, and serialization.
"""

import pytest
from app.models.schemas import (
    Company,
    Contact,
    EmailRecord,
    OutreachMessage,
    PipelineResult,
    PipelineStage,
    StageResult,
)


class TestCompany:
    """Tests for the Company model."""

    def test_create_company(self):
        company = Company(domain="notion.so", name="Notion")
        assert company.domain == "notion.so"
        assert company.name == "Notion"

    def test_domain_normalization(self):
        """Domain should be stripped of protocol and normalized."""
        company = Company(domain="https://www.Notion.so/", name="Notion")
        assert company.domain == "notion.so"

    def test_domain_strips_http(self):
        company = Company(domain="http://example.com", name="Example")
        assert company.domain == "example.com"

    def test_empty_fields_default(self):
        company = Company(domain="test.com")
        assert company.name == ""
        assert company.industry == ""
        assert company.size == ""
        assert company.country == ""


class TestContact:
    """Tests for the Contact model."""

    def test_create_contact(self):
        contact = Contact(
            first_name="John",
            last_name="Doe",
            title="VP of Engineering",
            company_domain="notion.so",
        )
        assert contact.display_name == "John Doe"

    def test_display_name_full_name(self):
        contact = Contact(full_name="Jane Smith")
        assert contact.display_name == "Jane Smith"

    def test_display_name_fallback(self):
        contact = Contact()
        assert contact.display_name == "Unknown"

    def test_display_name_first_only(self):
        contact = Contact(first_name="Jane")
        assert contact.display_name == "Jane"


class TestEmailRecord:
    """Tests for the EmailRecord model."""

    def test_create_email_record(self):
        record = EmailRecord(
            email="john@notion.so",
            contact_name="John Doe",
            company_domain="notion.so",
        )
        assert record.email == "john@notion.so"
        assert record.verification_status == "unknown"

    def test_source_field(self):
        record = EmailRecord(email="test@test.com", source="prospeo")
        assert record.source == "prospeo"


class TestOutreachMessage:
    """Tests for the OutreachMessage model."""

    def test_create_message(self):
        msg = OutreachMessage(
            to_email="john@notion.so",
            subject="Hello",
            body_html="<p>Hi</p>",
        )
        assert msg.status == "pending"
        assert msg.sent_at is None

    def test_default_status_is_pending(self):
        msg = OutreachMessage(
            to_email="test@test.com",
            subject="Test",
            body_html="<p>Test</p>",
        )
        assert msg.status == "pending"


class TestPipelineResult:
    """Tests for the PipelineResult model."""

    def test_create_result(self):
        result = PipelineResult(
            run_id="abc123",
            seed_domain="notion.so",
        )
        assert result.run_id == "abc123"
        assert result.total_companies == 0
        assert result.companies == []

    def test_success_rate_zero_emails(self):
        result = PipelineResult(run_id="test", seed_domain="test.com")
        assert result.success_rate == 0.0

    def test_success_rate_calculation(self):
        result = PipelineResult(
            run_id="test",
            seed_domain="test.com",
            total_emails=10,
            total_sent=8,
        )
        assert result.success_rate == 80.0
