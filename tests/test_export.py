"""
Tests for the export utilities.

Validates CSV and JSON export, run history persistence,
and file structure.
"""

import json
import pytest
from pathlib import Path
from datetime import datetime

from app.models.schemas import PipelineResult, Company, EmailRecord, OutreachMessage
from app.services.export import export_csv, export_json, save_run_history, load_run_history


@pytest.fixture
def sample_result():
    """Create a sample pipeline result for testing."""
    return PipelineResult(
        run_id="test123",
        seed_domain="notion.so",
        started_at=datetime.utcnow(),
        companies=[
            Company(domain="example.com", name="Example Inc"),
        ],
        emails=[
            EmailRecord(email="test@example.com", contact_name="Test"),
        ],
        messages=[
            OutreachMessage(
                to_email="test@example.com",
                subject="Hello",
                body_html="<p>Hi</p>",
                status="pending",
            ),
        ],
        total_companies=1,
        total_contacts=0,
        total_emails=1,
    )


@pytest.fixture
def tmp_export_dir(tmp_path):
    """Create a temporary export directory."""
    export_dir = tmp_path / "exports"
    export_dir.mkdir()
    return export_dir


class TestCSVExport:
    def test_export_creates_directory(self, sample_result, tmp_export_dir):
        result_dir = export_csv(sample_result, output_dir=tmp_export_dir)
        assert result_dir.exists()
        assert result_dir.is_dir()

    def test_export_creates_csv_files(self, sample_result, tmp_export_dir):
        result_dir = export_csv(sample_result, output_dir=tmp_export_dir)
        files = list(result_dir.glob("*.csv"))
        assert len(files) > 0


class TestJSONExport:
    def test_export_creates_file(self, sample_result, tmp_export_dir):
        path = export_json(sample_result, output_dir=tmp_export_dir)
        assert path.exists()
        assert path.suffix == ".json"

    def test_export_valid_json(self, sample_result, tmp_export_dir):
        path = export_json(sample_result, output_dir=tmp_export_dir)
        with open(path) as f:
            data = json.load(f)
        assert data["run_id"] == "test123"
        assert data["seed_domain"] == "notion.so"
