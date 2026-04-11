"""
Campaign Creator Pipeline
URL → scrape → Claude brand analysis → ad copy + creative variants → campaign record
"""
import json

import anthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from ai.scraper import scrape_url
from config import settings

client = anthropic.Anthropic(api_key=settings.anthropic_api_key)


BRAND_ANALYSIS_PROMPT = """You are an expert performance marketer and brand strategist.

Given the following scraped content from a product/brand page, extract structured intelligence
that will be used to automatically generate an ad campaign.

Scraped page content:
URL: {url}
Title: {title}
Description: {description}
Body text: {body_text}

Return a JSON object with exactly this structure:
{{
  "brand_name": "string — concise brand/product name",
  "brand_description": "string — 1-2 sentence brand summary",
  "value_propositions": ["string", "..."],
  "target_audience": {{
    "demographics": "string — age range, gender, income, location if inferable",
    "interests": ["string", "..."],
    "pain_points": ["string", "..."],
    "job_to_be_done": "string — what problem this product solves"
  }},
  "tone_of_voice": "string — e.g. 'professional and authoritative', 'playful and casual'",
  "suggested_categories": ["iab-category-slug", "..."],
  "bid_floor_cpm_usd": number,
  "key_product_features": ["string", "..."]
}}

For bid_floor_cpm_usd: estimate a reasonable floor CPM in USD based on the product category and
typical advertiser willingness to pay (e.g. SaaS=8-15, ecommerce=3-6, finance=15-25).
Return ONLY the JSON object, no explanation."""


CREATIVE_GENERATION_PROMPT = """You are a world-class ad copywriter.

Brand intelligence:
{brand_json}

Generate 3 distinct ad creative variants. Each variant should appeal to a different angle of the
target audience. Each creative must include:
- A short headline (max 30 chars)
- A longer headline (max 60 chars)
- Body copy (max 90 chars)
- Call-to-action text (max 15 chars)
- Creative concept description (what the visual should show — 1 sentence)
- Ad format suitability: list which formats this works for from: [banner, native, interstitial, social]

Return a JSON array of 3 creative objects:
[
  {{
    "variant_id": "A",
    "headline_short": "string",
    "headline_long": "string",
    "body_copy": "string",
    "cta": "string",
    "visual_concept": "string",
    "formats": ["string"]
  }},
  ...
]

Return ONLY the JSON array, no explanation."""


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _call_claude(prompt: str, max_tokens: int = 1024) -> str:
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def _parse_json(raw: str) -> dict | list:
    """Strip markdown code fences if present, then parse JSON."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.rsplit("```", 1)[0]
    return json.loads(text.strip())


async def create_campaign_from_url(product_url: str) -> dict:
    """
    Full pipeline: URL → scraped content → brand analysis → ad creatives → campaign dict.
    Returns a dict ready to populate a Campaign model.
    """
    # Step 1: Scrape
    page = await scrape_url(product_url)

    # Step 2: Brand analysis
    brand_prompt = BRAND_ANALYSIS_PROMPT.format(
        url=page["url"],
        title=page["title"],
        description=page["description"],
        body_text=page["body_text"],
    )
    brand_raw = _call_claude(brand_prompt, max_tokens=1024)
    brand_intel = _parse_json(brand_raw)

    # Step 3: Creative generation
    creative_prompt = CREATIVE_GENERATION_PROMPT.format(
        brand_json=json.dumps(brand_intel, indent=2)
    )
    creative_raw = _call_claude(creative_prompt, max_tokens=2048)
    creatives = _parse_json(creative_raw)

    return {
        "product_url": product_url,
        "brand_name": brand_intel.get("brand_name"),
        "brand_description": brand_intel.get("brand_description"),
        "value_propositions": brand_intel.get("value_propositions", []),
        "target_audience": brand_intel.get("target_audience", {}),
        "tone_of_voice": brand_intel.get("tone_of_voice"),
        "suggested_categories": brand_intel.get("suggested_categories", []),
        "bid_floor_cpm": brand_intel.get("bid_floor_cpm_usd"),
        "ad_creatives": creatives,
        "source_page": {
            "title": page["title"],
            "og_image": page["og_image"],
            "images": page["images"],
        },
    }
