"""
OutreachPilot — CLI Application
================================

Production CLI interface for the outreach automation pipeline.
Uses Rich for beautiful terminal output with progress indicators,
tables, and styled text.

Usage:
    python main.py
    python main.py --dry-run
    python main.py --domain notion.so
    python main.py --domain notion.so --dry-run --export csv
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import re

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Prompt, Confirm
from rich.rule import Rule
from rich.markdown import Markdown

from app.config.logging import configure_logging
from app.config.settings import get_settings
from app.services.pipeline import PipelineOrchestrator
from app.services.export import export_csv, export_json, save_run_history
from app.models.schemas import PipelineResult


# Ensure UTF-8 encoding on Windows to prevent UnicodeEncodeError
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

import io
if sys.platform == 'win32' and hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

console = Console()


# ── Branding ─────────────────────────────────────────────────

BANNER = """
[bold cyan]
  +===========================================================+
  |                                                           |
  |              O U T R E A C H  P I L O T                   |
  |                                                           |
  |          [bold white]OutreachPilot v1.0[/bold white]  --  Automated Outreach         |
  |                                                           |
  +===========================================================+
[/bold cyan]"""


def validate_domain(domain: str) -> str:
    """Validate and normalize a company domain input."""
    domain = domain.strip().lower()

    # Strip protocol
    for prefix in ("https://", "http://", "www."):
        if domain.startswith(prefix):
            domain = domain[len(prefix):]
    domain = domain.rstrip("/")

    # Basic validation
    if not domain:
        raise ValueError("Domain cannot be empty")
    if "." not in domain:
        raise ValueError(f"Invalid domain: {domain}")
    if not re.match(r'^[a-z0-9]([a-z0-9\-]*[a-z0-9])?(\.[a-z]{2,})+$', domain):
        raise ValueError(f"Invalid domain format: {domain}")

    return domain


def display_summary(result: PipelineResult) -> None:
    """Display the pipeline execution summary."""
    console.print()
    console.print(Rule("[bold cyan]PIPELINE SUMMARY[/bold cyan]", style="cyan"))
    console.print()

    # Stats table
    stats_table = Table(show_header=False, box=None, padding=(0, 2))
    stats_table.add_column("Metric", style="dim")
    stats_table.add_column("Value", style="bold white")

    stats_table.add_row("Seed Domain", f"[cyan]{result.seed_domain}[/cyan]")
    stats_table.add_row("Run ID", f"[dim]{result.run_id}[/dim]")
    stats_table.add_row("", "")
    stats_table.add_row("Companies Found", f"[green]{result.total_companies}[/green]")
    stats_table.add_row("Contacts Found", f"[green]{result.total_contacts}[/green]")
    stats_table.add_row("Emails Resolved", f"[green]{result.total_emails}[/green]")
    stats_table.add_row("Messages Ready", f"[green]{len(result.messages)}[/green]")

    if result.failed_contacts:
        stats_table.add_row("Failed Contacts", f"[yellow]{len(result.failed_contacts)}[/yellow]")

    if result.duration_seconds:
        stats_table.add_row("Duration", f"[dim]{result.duration_seconds:.1f}s[/dim]")

    console.print(Panel(stats_table, title="[bold]Results[/bold]", border_style="cyan", padding=(1, 2)))

    # Stage breakdown
    if result.stages:
        console.print()
        stage_table = Table(title="Stage Breakdown", border_style="dim")
        stage_table.add_column("Stage", style="bold")
        stage_table.add_column("Status", justify="center")
        stage_table.add_column("Count", justify="right")
        stage_table.add_column("Duration", justify="right")
        stage_table.add_column("Errors", justify="right")

        for stage in result.stages:
            status = "[green]✓[/green]" if stage.success else "[red]✗[/red]"
            stage_table.add_row(
                stage.stage.value.replace("_", " ").title(),
                status,
                str(stage.count),
                f"{stage.duration_seconds:.1f}s",
                str(len(stage.errors)) if stage.errors else "0",
            )

        console.print(stage_table)


def display_email_preview(result: PipelineResult, count: int = 3) -> None:
    """Display a preview of generated outreach emails."""
    if not result.messages:
        console.print("[yellow]No messages to preview.[/yellow]")
        return

    console.print()
    console.print(Rule("[bold cyan]EMAIL PREVIEW[/bold cyan]", style="cyan"))
    console.print()

    for i, msg in enumerate(result.messages[:count], 1):
        preview_panel = Panel(
            f"[bold]To:[/bold] {msg.to_name} <{msg.to_email}>\n"
            f"[bold]Company:[/bold] {msg.company_name}\n"
            f"[bold]Subject:[/bold] {msg.subject}\n\n"
            f"[dim]{msg.body_text[:300]}{'...' if len(msg.body_text) > 300 else ''}[/dim]",
            title=f"[bold]Email {i} of {len(result.messages)}[/bold]",
            border_style="blue",
            padding=(1, 2),
        )
        console.print(preview_panel)

    if len(result.messages) > count:
        console.print(f"[dim]  ... and {len(result.messages) - count} more emails[/dim]")


def display_send_summary(result: PipelineResult) -> None:
    """Display the send results."""
    console.print()
    console.print(Rule("[bold cyan]SEND RESULTS[/bold cyan]", style="cyan"))
    console.print()

    sent = sum(1 for m in result.messages if m.status == "sent")
    failed = sum(1 for m in result.messages if m.status == "failed")
    dry_run = sum(1 for m in result.messages if m.status == "dry_run")

    results_table = Table(show_header=False, box=None, padding=(0, 2))
    results_table.add_column("Metric", style="dim")
    results_table.add_column("Value", style="bold")

    if dry_run > 0:
        results_table.add_row("Dry Run", f"[blue]{dry_run}[/blue]")
    if sent > 0:
        results_table.add_row("Sent", f"[green]{sent}[/green]")
    if failed > 0:
        results_table.add_row("Failed", f"[red]{failed}[/red]")

    console.print(Panel(results_table, title="[bold]Send Summary[/bold]", border_style="green" if failed == 0 else "yellow"))


async def run_pipeline_cli(domain: str, dry_run: bool = False, export: str = "") -> None:
    """Execute the full pipeline with CLI feedback."""
    settings = get_settings()

    def progress_callback(stage: str = "", message: str = "", done: bool = False, **kwargs):
        icon = "[green]✓[/green]" if done else "[cyan]⟳[/cyan]"
        console.print(f"  {icon} {message}")

    pipeline = PipelineOrchestrator(progress_callback=progress_callback)

    try:
        console.print()
        console.print(f"[bold cyan]Starting pipeline for:[/bold cyan] [white]{domain}[/white]")
        console.print()

        # Run the discovery pipeline
        result = await pipeline.run(domain, dry_run=dry_run)

        # Display summary
        display_summary(result)

        if not result.messages:
            console.print("\n[yellow]No outreach messages were generated. Pipeline complete.[/yellow]")
            save_run_history(result)
            return

        # Display email preview
        display_email_preview(result)

        # Safety checkpoint
        console.print()
        console.print(Rule("[bold yellow]SAFETY CHECKPOINT[/bold yellow]", style="yellow"))
        console.print()

        checkpoint_panel = Panel(
            f"[bold]Ready to send {len(result.messages)} emails[/bold]\n\n"
            f"  Companies:  [cyan]{result.total_companies}[/cyan]\n"
            f"  Contacts:   [cyan]{result.total_contacts}[/cyan]\n"
            f"  Emails:     [cyan]{result.total_emails}[/cyan]\n"
            f"  Messages:   [cyan]{len(result.messages)}[/cyan]\n"
            f"  Mode:       [{'blue]Dry Run' if dry_run else 'green]Live Send'}[/]\n",
            title="[bold yellow]⚠ Confirm Before Sending[/bold yellow]",
            border_style="yellow",
            padding=(1, 2),
        )
        console.print(checkpoint_panel)

        proceed = Confirm.ask(
            "[bold]Proceed with sending?[/bold]",
            default=False,
        )

        if not proceed:
            console.print("\n[yellow]Aborted. No emails were sent.[/yellow]")
            save_run_history(result)
            return

        # Send emails
        console.print()
        result = await pipeline.send(result, dry_run=dry_run)
        display_send_summary(result)

        # Export results
        if export in ("csv", "both"):
            csv_path = export_csv(result)
            console.print(f"\n[green]✓ CSV exported to:[/green] {csv_path}")

        if export in ("json", "both"):
            json_path = export_json(result)
            console.print(f"[green]✓ JSON exported to:[/green] {json_path}")

        if not export:
            do_export = Confirm.ask("\n[bold]Export results?[/bold]", default=True)
            if do_export:
                csv_path = export_csv(result)
                json_path = export_json(result)
                console.print(f"\n[green]✓ CSV exported to:[/green]  {csv_path}")
                console.print(f"[green]✓ JSON exported to:[/green] {json_path}")

        # Save run history
        save_run_history(result)
        console.print(f"\n[dim]Run {result.run_id} saved to history.[/dim]")

    except KeyboardInterrupt:
        console.print("\n[yellow]Pipeline interrupted by user.[/yellow]")
    except Exception as exc:
        console.print(f"\n[red]Pipeline error: {exc}[/red]")
        raise
    finally:
        await pipeline.close()


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="OutreachPilot — Automated B2B Outreach Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--domain", "-d",
        type=str,
        help="Target company domain (e.g., notion.so)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run pipeline without actually sending emails",
    )
    parser.add_argument(
        "--export",
        choices=["csv", "json", "both"],
        default="",
        help="Auto-export results in the specified format",
    )
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="Launch the web dashboard instead of CLI",
    )
    return parser.parse_args()


def main() -> None:
    """Entry point for the CLI application."""
    configure_logging()
    args = parse_args()

    # Launch dashboard mode
    if args.dashboard:
        import uvicorn
        from app.dashboard.app import create_app

        settings = get_settings()
        app = create_app()
        console.print(BANNER)
        console.print(f"[bold green]Dashboard running at:[/bold green] http://localhost:{settings.dashboard_port}")
        uvicorn.run(app, host=settings.dashboard_host, port=settings.dashboard_port)
        return

    # CLI mode
    console.print(BANNER)

    # Get domain
    domain = args.domain
    if not domain:
        domain = Prompt.ask("[bold cyan]Enter company domain[/bold cyan]")

    try:
        domain = validate_domain(domain)
    except ValueError as exc:
        console.print(f"[red]Invalid domain: {exc}[/red]")
        sys.exit(1)

    # Run pipeline
    asyncio.run(run_pipeline_cli(domain, dry_run=args.dry_run, export=args.export))


if __name__ == "__main__":
    main()
