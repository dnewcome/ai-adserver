"""Scrape product/publisher pages to extract raw content for AI analysis."""
import re

import aiohttp
from bs4 import BeautifulSoup


async def scrape_url(url: str, timeout: int = 15) -> dict:
    """Fetch a URL and return structured text content."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; AIAdServer/1.0; +https://aiadserver.io/bot)"
        )
    }
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            resp.raise_for_status()
            html = await resp.text()

    soup = BeautifulSoup(html, "html.parser")

    # Strip scripts, styles, nav boilerplate
    for tag in soup(["script", "style", "nav", "footer", "iframe"]):
        tag.decompose()

    title = soup.title.string.strip() if soup.title else ""

    # Meta tags
    meta: dict[str, str] = {}
    for m in soup.find_all("meta"):
        name = m.get("name") or m.get("property") or ""
        content = m.get("content") or ""
        if name and content:
            meta[name.lower()] = content

    description = meta.get("description") or meta.get("og:description") or ""
    og_title = meta.get("og:title") or title
    og_image = meta.get("og:image") or ""

    # Collect visible text (first 4000 chars to keep prompt lean)
    body_text = re.sub(r"\s+", " ", soup.get_text(separator=" ")).strip()[:4000]

    # Images
    images = [
        img["src"] for img in soup.find_all("img", src=True)
        if not img["src"].startswith("data:")
    ][:10]

    return {
        "url": url,
        "title": og_title or title,
        "description": description,
        "og_image": og_image,
        "body_text": body_text,
        "images": images,
        "meta": meta,
    }
