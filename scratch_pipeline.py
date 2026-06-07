import asyncio
from app.services.pipeline import PipelineOrchestrator

async def test_pipeline():
    pipeline = PipelineOrchestrator(progress_callback=lambda stage, message, **kw: print(f"[{stage}] {message}"))
    result = await pipeline.run("droip.com", max_companies=2, max_contacts_per_company=2)
    print("\n--- Pipeline Result ---")
    print(f"Companies: {len(result.companies)}")
    print(f"Contacts: {len(result.contacts)}")
    print(f"Emails: {len(result.emails)}")
    print(f"Messages generated: {len(result.messages)}")
    for m in result.messages:
        print(f"\nTo: {m.to_email} ({m.to_name})")
        print(f"Subject: {m.subject}")
        print(f"Status: {m.status}")

if __name__ == "__main__":
    asyncio.run(test_pipeline())
