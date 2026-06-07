"""
Unit tests for the email generator.

Validates template generation, deduplication,
and deterministic template selection.
"""

import pytest
from app.services.email_generator import (
    generate_outreach_message,
    generate_batch_messages,
    _shorten_role,
    _select_template_index,
)
from app.models.schemas import EmailRecord


class TestEmailGenerator:
    """Tests for email generation logic."""

    def test_generate_message(self):
        record = EmailRecord(
            email="john@notion.so",
            contact_name="John Doe",
            contact_title="VP of Engineering",
            company_name="Notion",
            company_domain="notion.so",
        )
        msg = generate_outreach_message(record)
        assert msg.to_email == "john@notion.so"
        assert msg.to_name == "John Doe"
        assert "John" in msg.body_html
        assert "Notion" in msg.body_html
        assert msg.subject != ""

    def test_deterministic_template(self):
        """Same email should always produce the same template."""
        record = EmailRecord(
            email="test@example.com",
            contact_name="Test User",
            company_name="Example",
        )
        msg1 = generate_outreach_message(record)
        msg2 = generate_outreach_message(record)
        assert msg1.subject == msg2.subject
        assert msg1.body_html == msg2.body_html

    def test_batch_deduplication(self):
        """Duplicate emails should be removed from batch."""
        records = [
            EmailRecord(email="same@test.com", contact_name="Person A"),
            EmailRecord(email="same@test.com", contact_name="Person B"),
            EmailRecord(email="different@test.com", contact_name="Person C"),
        ]
        messages = generate_batch_messages(records)
        assert len(messages) == 2

    def test_shorten_role(self):
        assert _shorten_role("VP of Engineering") == "VP of Engineering"
        assert _shorten_role("") == "leader"

    def test_template_index_is_deterministic(self):
        idx1 = _select_template_index("test@example.com")
        idx2 = _select_template_index("test@example.com")
        assert idx1 == idx2

    def test_different_emails_can_get_different_templates(self):
        """Different emails should potentially get different templates."""
        indices = set()
        for i in range(20):
            idx = _select_template_index(f"user{i}@company{i}.com")
            indices.add(idx)
        # With 20 different emails, we should get at least 2 different templates
        assert len(indices) >= 2
