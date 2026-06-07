"""
FastAPI Web Dashboard Application.

A lightweight web interface for the OutreachPilot pipeline.
Built with FastAPI + Jinja2 + HTMX for a responsive SaaS-style experience.

Pages:
  /                — Domain input
  /run             — Pipeline execution
  /results/{id}    — Results dashboard
  /preview/{id}    — Email preview
  /approve/{id}    — Approval screen
  /history         — Run history
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config.logging import configure_logging, get_logger
from app.config.settings import get_settings
from app.services.pipeline import PipelineOrchestrator
from app.services.export import export_csv, export_json, save_run_history, load_run_history
from app.models.schemas import PipelineResult


logger = get_logger("dashboard")

# In-memory store for active pipeline runs
# In production, this would be Redis or a database
_active_runs: Dict[str, PipelineResult] = {}
_run_status: Dict[str, dict] = {}


def create_app() -> FastAPI:
    """Factory function to create the FastAPI application."""
    configure_logging()
    settings = get_settings()

    app = FastAPI(
        title="OutreachPilot Dashboard",
        description="Automated B2B Outreach Pipeline",
        version="1.0.0",
    )

    # Static files
    static_dir = settings.static_dir
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # Templates
    templates = Jinja2Templates(directory=str(settings.templates_dir))

    # Custom template filters
    templates.env.filters["timeago"] = _timeago_filter
    templates.env.globals["now"] = datetime.utcnow

    # ── Routes ───────────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        """Domain input page."""
        history = load_run_history()
        return templates.TemplateResponse("index.html", {
            "request": request,
            "history": history[-5:] if history else [],
        })

    @app.post("/run", response_class=HTMLResponse)
    async def start_run(request: Request, domain: str = Form(...), dry_run: Optional[str] = Form(None)):
        """Start a new pipeline run."""
        # Parse dry_run checkbox (HTML checkboxes send string "true" or nothing)
        is_dry_run = dry_run is not None and dry_run.lower() in ("true", "on", "1", "yes")

        # Validate domain
        domain = domain.strip().lower()
        for prefix in ("https://", "http://", "www."):
            if domain.startswith(prefix):
                domain = domain[len(prefix):]
        domain = domain.rstrip("/")

        if not domain or "." not in domain:
            return templates.TemplateResponse("index.html", {
                "request": request,
                "error": "Please enter a valid domain (e.g., notion.so)",
                "history": load_run_history()[-5:],
            })

        run_id = str(uuid.uuid4())[:8]
        _run_status[run_id] = {
            "domain": domain,
            "dry_run": is_dry_run,
            "status": "running",
            "current_stage": "Initializing...",
            "stages": [],
            "started_at": datetime.utcnow().isoformat(),
        }

        # Start pipeline in background
        asyncio.create_task(_execute_pipeline(run_id, domain, is_dry_run))

        return templates.TemplateResponse("running.html", {
            "request": request,
            "run_id": run_id,
            "domain": domain,
            "dry_run": is_dry_run,
        })

    @app.get("/status/{run_id}", response_class=JSONResponse)
    async def get_status(run_id: str):
        """HTMX polling endpoint for pipeline status."""
        status = _run_status.get(run_id)
        if not status:
            return JSONResponse({"error": "Run not found"}, status_code=404)
        return JSONResponse(status)

    @app.get("/results/{run_id}", response_class=HTMLResponse)
    async def results(request: Request, run_id: str):
        """Results dashboard."""
        result = _active_runs.get(run_id)
        if not result:
            return templates.TemplateResponse("error.html", {
                "request": request,
                "error": "Run not found or expired. The run may have completed before data could be stored, or the server was restarted.",
            })

        return templates.TemplateResponse("results.html", {
            "request": request,
            "result": result,
        })

    @app.get("/preview/{run_id}", response_class=HTMLResponse)
    async def preview_emails(request: Request, run_id: str):
        """Email preview page."""
        result = _active_runs.get(run_id)
        if not result:
            return templates.TemplateResponse("error.html", {
                "request": request,
                "error": "Run not found or expired.",
            })

        return templates.TemplateResponse("preview.html", {
            "request": request,
            "result": result,
        })

    @app.get("/approve/{run_id}", response_class=HTMLResponse)
    async def approve_page(request: Request, run_id: str):
        """Approval screen before sending."""
        result = _active_runs.get(run_id)
        if not result:
            return templates.TemplateResponse("error.html", {
                "request": request,
                "error": "Run not found or expired.",
            })

        return templates.TemplateResponse("approve.html", {
            "request": request,
            "result": result,
        })

    @app.post("/send/{run_id}", response_class=HTMLResponse)
    async def send_emails(request: Request, run_id: str):
        """Execute email sending after approval."""
        result = _active_runs.get(run_id)
        if not result:
            return templates.TemplateResponse("error.html", {
                "request": request,
                "error": "Run not found or expired.",
            })

        pipeline = PipelineOrchestrator()
        try:
            result = await pipeline.send(result, dry_run=result.dry_run)
            _active_runs[run_id] = result

            # Save exports and history
            try:
                export_csv(result)
                export_json(result)
            except Exception as exc:
                logger.warning("export_failed", error=str(exc))
            save_run_history(result)
        except Exception as exc:
            logger.error("send_failed", run_id=run_id, error=str(exc))
            return templates.TemplateResponse("error.html", {
                "request": request,
                "error": f"Failed to send emails: {exc}",
            })
        finally:
            await pipeline.close()

        return templates.TemplateResponse("summary.html", {
            "request": request,
            "result": result,
        })

    @app.get("/history", response_class=HTMLResponse)
    async def history(request: Request):
        """Run history page."""
        runs = load_run_history()
        runs.reverse()  # Most recent first
        return templates.TemplateResponse("history.html", {
            "request": request,
            "runs": runs,
        })

    @app.get("/api/health")
    async def health_check():
        """Health check endpoint."""
        return {"status": "healthy", "version": "1.0.0"}

    return app


async def _execute_pipeline(run_id: str, domain: str, dry_run: bool) -> None:
    """Background task to execute the pipeline."""
    def progress_callback(stage: str = "", message: str = "", done: bool = False, **kwargs):
        if run_id in _run_status:
            _run_status[run_id]["current_stage"] = message
            if done:
                _run_status[run_id]["stages"].append({
                    "stage": stage,
                    "message": message,
                    "done": True,
                })

    pipeline = PipelineOrchestrator(progress_callback=progress_callback)

    try:
        result = await pipeline.run(domain, dry_run=dry_run, run_id=run_id)
        _active_runs[run_id] = result
        _run_status[run_id]["status"] = "completed"
        _run_status[run_id]["current_stage"] = "Pipeline complete"
        _run_status[run_id]["total_companies"] = result.total_companies
        _run_status[run_id]["total_contacts"] = result.total_contacts
        _run_status[run_id]["total_emails"] = result.total_emails
        _run_status[run_id]["total_messages"] = len(result.messages)

        # Auto-save run history
        try:
            save_run_history(result)
        except Exception as exc:
            logger.warning("auto_save_history_failed", error=str(exc))

    except Exception as exc:
        logger.error("pipeline_background_error", run_id=run_id, error=str(exc))
        _run_status[run_id]["status"] = "failed"
        _run_status[run_id]["current_stage"] = f"Error: {exc}"
    finally:
        await pipeline.close()


def _timeago_filter(dt_str: str) -> str:
    """Convert an ISO datetime string to a human-readable 'time ago' string."""
    try:
        if isinstance(dt_str, datetime):
            dt = dt_str
        else:
            dt = datetime.fromisoformat(str(dt_str))
        diff = datetime.utcnow() - dt
        seconds = diff.total_seconds()

        if seconds < 60:
            return "just now"
        elif seconds < 3600:
            return f"{int(seconds // 60)}m ago"
        elif seconds < 86400:
            return f"{int(seconds // 3600)}h ago"
        else:
            return f"{int(seconds // 86400)}d ago"
    except (ValueError, TypeError):
        return str(dt_str)
