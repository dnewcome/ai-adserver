"""
Publisher Analyzer Pipeline
Website URL → scrape → Claude placement recommendations → inventory zones + serve tags
"""
import json

from tenacity import retry, stop_after_attempt, wait_exponential

import anthropic
from ai.scraper import scrape_url
from config import settings

client = anthropic.Anthropic(api_key=settings.anthropic_api_key)


PUBLISHER_ANALYSIS_PROMPT = """You are an expert ad monetization consultant and UX specialist.

A publisher wants to monetize their website. Analyze the page below and recommend the best
ad inventory zones to maximize revenue without hurting user experience.

Page content:
URL: {url}
Title: {title}
Description: {description}
Body text snippet: {body_text}

Return a JSON object:
{{
  "site_summary": "string — 2-3 sentence summary of the site's content/audience",
  "audience_profile": {{
    "niche": "string",
    "estimated_demographics": "string",
    "content_categories": ["iab-slug", "..."]
  }},
  "recommended_zones": [
    {{
      "name": "string — slug like 'above-fold-leaderboard'",
      "zone_type": "banner | native | interstitial | video",
      "dimensions": "string — e.g. '728x90' or '300x250'",
      "page_location": "string — where on the page e.g. 'Top of page, above the fold'",
      "placement_rationale": "string — why this placement converts well here",
      "recommended_cpm_usd": number,
      "categories": ["iab-slug", "..."]
    }}
  ],
  "conversion_tips": ["string — actionable tip to improve ad performance", "..."],
  "estimated_monthly_revenue_usd": {{
    "low": number,
    "high": number,
    "assumptions": "string"
  }}
}}

Recommend 3-5 zones. Prioritize high-viewability placements. Return ONLY the JSON."""


INSTAGRAM_MONETIZATION_PROMPT = """You are a top-tier social media monetization strategist.

An Instagram creator wants to monetize their account. Based on the profile information below,
provide a comprehensive monetization strategy.

Instagram handle: @{handle}
Follower count: {followers}
Engagement rate: {engagement_rate}%
Content niche: {niche}
Top content themes: {themes}
Bio: {bio}

Return a JSON object:
{{
  "monetization_score": number (1-10, overall monetization potential),
  "primary_niche": "string",
  "audience_value": "string — why advertisers would pay for this audience",
  "strategies": [
    {{
      "type": "sponsored_posts | affiliate | digital_products | subscriptions | brand_deals | ad_inventory",
      "title": "string",
      "description": "string",
      "estimated_monthly_income_usd": {{ "low": number, "high": number }},
      "effort_level": "low | medium | high",
      "how_to_start": "string — concrete first step"
    }}
  ],
  "affiliate_programs": [
    {{
      "program": "string — program name",
      "category": "string",
      "commission_rate": "string — e.g. '5-10%'",
      "why_it_fits": "string",
      "signup_url_hint": "string — describe where to find it, do not fabricate URLs"
    }}
  ],
  "sponsored_post_rate": {{
    "story": number,
    "feed_post": number,
    "reel": number,
    "notes": "string"
  }},
  "media_kit_highlights": ["string", "..."],
  "growth_actions": ["string — actionable tip to grow monetization", "..."]
}}

Return ONLY the JSON."""


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _call_claude(prompt: str, max_tokens: int = 2048) -> str:
    client_local = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    response = client_local.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def _parse_json(raw: str) -> dict | list:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.rsplit("```", 1)[0]
    return json.loads(text.strip())


async def analyze_publisher_site(site_url: str) -> dict:
    """Scrape a publisher's site and return AI-recommended inventory zones."""
    page = await scrape_url(site_url)

    prompt = PUBLISHER_ANALYSIS_PROMPT.format(
        url=page["url"],
        title=page["title"],
        description=page["description"],
        body_text=page["body_text"],
    )
    raw = _call_claude(prompt)
    analysis = _parse_json(raw)

    # Attach serve tag snippet to each zone
    for zone in analysis.get("recommended_zones", []):
        zone["serve_tag"] = _generate_serve_tag(site_url, zone["name"])

    return {"site_url": site_url, "page_title": page["title"], **analysis}


def _generate_serve_tag(site_url: str, zone_name: str) -> str:
    """Generate the JS snippet a publisher pastes into their site."""
    return (
        f'<!-- AI Ad Server | Zone: {zone_name} -->\n'
        f'<div id="aias-{zone_name}"></div>\n'
        f'<script>\n'
        f'  (function(){{ var s=document.createElement("script");\n'
        f'    s.src="https://cdn.aiadserver.io/serve.js";\n'
        f'    s.dataset.zone="{zone_name}";\n'
        f'    s.dataset.site="{site_url}";\n'
        f'    s.async=true;\n'
        f'    document.getElementById("aias-{zone_name}").appendChild(s);\n'
        f'  }})();\n'
        f'</script>'
    )


async def analyze_instagram(
    handle: str,
    followers: int,
    engagement_rate: float,
    niche: str,
    themes: list[str],
    bio: str,
) -> dict:
    """Generate a full monetization strategy for an Instagram account."""
    prompt = INSTAGRAM_MONETIZATION_PROMPT.format(
        handle=handle,
        followers=followers,
        engagement_rate=engagement_rate,
        niche=niche,
        themes=", ".join(themes),
        bio=bio,
    )
    raw = _call_claude(prompt, max_tokens=3000)
    return _parse_json(raw)
