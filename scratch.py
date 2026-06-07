import httpx
import asyncio

async def test_prospeo():
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-KEY": "pk_a5d0abe57c8df0dbb420e1672eb2f541d00d202e7a584ebb46161c6a85f0a51b",
    }
    async with httpx.AsyncClient(base_url="https://api.prospeo.io") as client:
        payload = {"company": "droip.com", "first_name": "John", "last_name": "Doe"}
        res = await client.post("/email-finder", json=payload, headers=headers)
        print("Finder:", res.status_code, res.text)

if __name__ == "__main__":
    asyncio.run(test_prospeo())
