"""
Smoke test for the two main AI pipelines.
Run with:  ANTHROPIC_API_KEY=sk-... python test_pipeline.py
"""
import asyncio
import json
import sys

from ai.campaign_creator import create_campaign_from_url
from ai.publisher_analyzer import analyze_instagram, analyze_publisher_site


async def test_campaign_creator():
    url = sys.argv[1] if len(sys.argv) > 1 else "https://stripe.com"
    print(f"\n=== Campaign Creator: {url} ===\n")
    result = await create_campaign_from_url(url)
    print(json.dumps(result, indent=2))


async def test_publisher_analyzer():
    url = sys.argv[2] if len(sys.argv) > 2 else "https://techcrunch.com"
    print(f"\n=== Publisher Analyzer: {url} ===\n")
    result = await analyze_publisher_site(url)
    print(json.dumps(result, indent=2))


async def test_instagram():
    print("\n=== Instagram Monetization ===\n")
    result = await analyze_instagram(
        handle="example_creator",
        followers=45000,
        engagement_rate=4.2,
        niche="fitness and wellness",
        themes=["workout routines", "healthy eating", "mindfulness", "gear reviews"],
        bio="Personal trainer | Helping you build strength & confidence 💪 | DMs open for coaching",
    )
    print(json.dumps(result, indent=2))


async def main():
    await test_campaign_creator()
    await test_publisher_analyzer()
    await test_instagram()


if __name__ == "__main__":
    asyncio.run(main())
