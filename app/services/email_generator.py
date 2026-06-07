"""
Email generation engine.

Creates personalized, professional outreach emails using
contact and company data. Uses OpenRouter LLM to generate
highly personalized and contextual messages.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from app.models.schemas import Contact, EmailRecord, OutreachMessage
from app.services.openrouter_service import OpenRouterService


# ── Email Templates ──────────────────────────────────────────

SUBJECT_TEMPLATES = [
    "Quick question for {company}",
    "Connecting with {company}'s {role_short}",
    "Exploring a partnership with {company}",
    "{first_name}, a brief intro",
    "Idea for {company}",
]

BODY_TEMPLATES = [
    # Template 1 — Direct & Concise
    """<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 14px; line-height: 1.6; color: #1a1a2e;">
<p>Hi {first_name},</p>

<p>I came across {company} while researching companies in your space and was impressed by what your team is building.</p>

<p>As {role}, you're likely focused on scaling operations efficiently. We've helped similar companies streamline their workflows and would love to explore if there's a fit.</p>

<p>Would you be open to a 15-minute call this week?</p>

<p>Best,<br>
{sender_name}</p>
</div>""",

    # Template 2 — Value-First
    """<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 14px; line-height: 1.6; color: #1a1a2e;">
<p>Hi {first_name},</p>

<p>I noticed {company} is growing rapidly — congratulations on the momentum.</p>

<p>In my experience working with companies at your stage, {role_short}s often face challenges around operational efficiency as teams scale. We've developed an approach that's helped teams like yours save 30%+ in process overhead.</p>

<p>Happy to share some insights — no strings attached. Would a brief chat work?</p>

<p>Cheers,<br>
{sender_name}</p>
</div>""",

    # Template 3 — Peer-Level
    """<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 14px; line-height: 1.6; color: #1a1a2e;">
<p>{first_name},</p>

<p>I'll keep this brief — I know your time as {role} at {company} is valuable.</p>

<p>We work with companies in your industry on solving [specific challenge]. I'd love to understand how {company} currently approaches this and see if there's a way we can help.</p>

<p>Open to connecting?</p>

<p>Thanks,<br>
{sender_name}</p>
</div>""",

    # Template 4 — Curiosity-Driven
    """<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 14px; line-height: 1.6; color: #1a1a2e;">
<p>Hi {first_name},</p>

<p>I've been following {company}'s progress and had a question about how your team handles growth-stage operations.</p>

<p>We recently helped a company in a similar position reduce their manual processes by 40%. Thought it might be relevant given {company}'s trajectory.</p>

<p>Worth a quick conversation?</p>

<p>Best regards,<br>
{sender_name}</p>
</div>""",
]

PLAIN_TEXT_TEMPLATES = [
    """Hi {first_name},

I came across {company} while researching companies in your space and was impressed by what your team is building.

As {role}, you're likely focused on scaling operations efficiently. We've helped similar companies streamline their workflows and would love to explore if there's a fit.

Would you be open to a 15-minute call this week?

Best,
{sender_name}""",

    """Hi {first_name},

I noticed {company} is growing rapidly — congratulations on the momentum.

In my experience working with companies at your stage, {role_short}s often face challenges around operational efficiency as teams scale. We've developed an approach that's helped teams like yours save 30%+ in process overhead.

Happy to share some insights — no strings attached. Would a brief chat work?

Cheers,
{sender_name}""",

    """{first_name},

I'll keep this brief — I know your time as {role} at {company} is valuable.

We work with companies in your industry on solving growth challenges. I'd love to understand how {company} currently approaches this and see if there's a way we can help.

Open to connecting?

Thanks,
{sender_name}""",

    """Hi {first_name},

I've been following {company}'s progress and had a question about how your team handles growth-stage operations.

We recently helped a company in a similar position reduce their manual processes by 40%. Thought it might be relevant given {company}'s trajectory.

Worth a quick conversation?

Best regards,
{sender_name}""",
]


def _shorten_role(title: str) -> str:
    """Extract a concise role label from a full job title."""
    if not title:
        return "leader"
    # Take first meaningful part
    parts = title.split(",")
    short = parts[0].strip()
    if len(short) > 30:
        short = short[:30].rsplit(" ", 1)[0]
    return short


def _select_template_index(email: str) -> int:
    """
    Deterministically select a template variant based on email hash.
    This ensures the same contact always gets the same template,
    but different contacts get variety.
    """
    h = hashlib.md5(email.encode()).hexdigest()
    return int(h, 16) % len(BODY_TEMPLATES)


async def generate_outreach_message(
    email_record: EmailRecord,
    sender_name: str = "The OutreachPilot Team",
) -> OutreachMessage:
    """
    Generate a personalized outreach email for a verified contact using OpenRouter.
    """
    first_name = email_record.contact_name.split()[0] if email_record.contact_name else "there"
    company = email_record.company_name or email_record.company_domain
    role = email_record.contact_title or "leader"

    system_prompt = (
        "You are an expert B2B sales copywriter. Your goal is to write a highly personalized, "
        "concise, and engaging outreach email. Avoid spammy language. Focus on value. "
        "You MUST return a JSON object with strictly these three keys:\n"
        "- 'subject': The email subject line\n"
        "- 'body_html': The HTML version of the email body\n"
        "- 'body_text': The plain text version of the email body"
    )

    prompt = (
        f"Write a personalized cold outreach email to {first_name}, who is the {role} at {company}. "
        f"The email is sent by {sender_name}. "
        f"Mention their role and company in a natural way. "
        f"Keep the email under 100 words. Make the HTML version clean and professional."
    )

    llm = OpenRouterService()
    try:
        result = await llm.generate_email(prompt=prompt, system_prompt=system_prompt)
        subject = result.get("subject", f"Quick question for {company}")
        body_html = result.get("body_html", f"<p>Hi {first_name},</p><p>Best,</p><p>{sender_name}</p>")
        body_text = result.get("body_text", f"Hi {first_name},\n\nBest,\n{sender_name}")
    except Exception as e:
        llm.logger.error("email_generation_failed", error=str(e), contact=email_record.email)
        # Fallback to simple template
        subject = f"Connecting with {company}"
        body_html = f"<p>Hi {first_name},</p><p>I'd love to connect and learn more about {company}.</p><p>Best,<br>{sender_name}</p>"
        body_text = f"Hi {first_name},\n\nI'd love to connect and learn more about {company}.\n\nBest,\n{sender_name}"

    return OutreachMessage(
        to_email=email_record.email,
        to_name=email_record.contact_name,
        to_title=email_record.contact_title,
        company_name=email_record.company_name,
        company_domain=email_record.company_domain,
        subject=subject,
        body_html=body_html,
        body_text=body_text,
    )


async def generate_batch_messages(
    email_records: list[EmailRecord],
    sender_name: str = "The OutreachPilot Team",
) -> list[OutreachMessage]:
    """Generate outreach messages for a batch of verified emails using LLM concurrently."""
    seen_emails: set[str] = set()
    unique_records = []

    for record in email_records:
        if record.email.lower() in seen_emails:
            continue
        seen_emails.add(record.email.lower())
        unique_records.append(record)

    # Process concurrently
    tasks = [
        generate_outreach_message(record, sender_name)
        for record in unique_records
    ]
    
    messages = await asyncio.gather(*tasks)
    return list(messages)
