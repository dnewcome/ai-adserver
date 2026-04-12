# AI Ad Server

A fully automated ad server powered by Claude and DALL-E 3. Give it a product URL and it scrapes the page, generates brand analysis, writes ad copy, and produces images — all without human input. Publishers submit their site URL and receive AI-recommended ad zones with ready-to-paste serve tags and revenue estimates.

## Architecture

```
Advertiser                Publisher
    │                         │
    ▼                         ▼
POST /campaigns/create    POST /publishers/analyze-site
    │                         │
    ▼                         ▼
Celery worker             Celery worker
  → scrape product URL      → scrape publisher site
  → Claude: brand analysis  → Claude: zone recommendations
  → Claude: ad copy (3 variants)  → save InventoryZone rows
  → DALL-E 3: images        → generate serve tags
  → save Campaign row
    │
    ▼ (at page load)
serve.js tag → GET /serve/{zone_id}
    → RTB auction (second-price)
    → winner's creative returned as JSON
    → rendered into the page
    → click → GET /auction/click/{impression_id} → redirect
```

**Stack:** FastAPI · SQLAlchemy 2 async · PostgreSQL · Redis · Celery · Claude (claude-sonnet-4-6) · DALL-E 3

---

## Environment setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

`.env` file (copy `.env.example`):

```env
DATABASE_URL=postgresql+asyncpg://adserver@/adserver?host=/var/run/postgresql&port=5433
REDIS_URL=redis://localhost:6379/0
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...          # for DALL-E 3 image generation
SECRET_KEY=change-me
```

Run migrations:

```bash
alembic upgrade head
```

Start services:

```bash
# API server
uvicorn main:app --reload --port 8000

# Celery worker (separate terminal)
celery -A workers.celery_app worker --loglevel=info --concurrency=2 -P solo
```

---

## Advertiser: creating a campaign

### 1. Register

```bash
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","password":"secret","role":"advertiser","company_name":"Acme"}'
```

Returns:
```json
{"access_token": "eyJ...", "token_type": "bearer", "role": "advertiser"}
```

### 2. Create a campaign

Pass your product URL. The AI does everything else.

```bash
curl -X POST http://localhost:8000/campaigns/create \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "product_url": "https://yourproduct.com",
    "daily_budget_usd": 50,
    "total_budget_usd": 500
  }'
```

Returns immediately with a job ID:
```json
{"job_id": "abc123", "status": "queued", "poll_url": "/jobs/abc123"}
```

### 3. Poll for completion

```bash
curl http://localhost:8000/jobs/abc123
```

```json
{
  "job_id": "abc123",
  "status": "done",
  "result": {"campaign_id": "uuid...", "status": "created"}
}
```

Once `status` is `done`, the campaign is live and bidding immediately. Images generate in the background — `images_status` on the campaign moves from `pending` → `done` when ready.

### 4. View your campaigns

```bash
curl http://localhost:8000/campaigns \
  -H "Authorization: Bearer <token>"
```

Each campaign includes:
- `brand_name`, `brand_description`, `tone_of_voice`
- `value_propositions` (array of strings)
- `target_audience` (age range, interests, platforms, pain points)
- `suggested_categories` (IAB taxonomy IDs)
- `bid_floor_cpm` (AI-suggested minimum CPM in USD)
- `ad_creatives` — 3 variants (A/B/C), each with:
  - `headline_short`, `headline_long`
  - `body_copy`, `cta`
  - `visual_concept` (the prompt sent to DALL-E)
  - `image_url` (once images are done, e.g. `/static/images/{campaign_id}/A.png`)

### Budget and spend

Advertiser accounts have a `balance_usd` field. The auction deducts the winning CPM from the advertiser's balance on every impression. When balance reaches zero, the campaign stops serving.

Balance can be set directly from the admin UI (see below), or via SQL:

```sql
UPDATE advertisers SET balance_usd = balance_usd + 100 WHERE email = 'you@example.com';
```

---

## Publisher: monetizing a site

### 1. Register as a publisher

```bash
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"pub@example.com","password":"secret","role":"publisher","site_url":"https://yoursite.com"}'
```

### 2. Analyze your site

Submit your URL — Claude scrapes it, recommends ad zones, estimates revenue, and generates serve tags.

```bash
curl -X POST http://localhost:8000/publishers/analyze-site \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"site_url": "https://yoursite.com"}'
```

Returns a job ID. Poll it:

```bash
curl http://localhost:8000/jobs/<job_id>
```

Result:
```json
{
  "status": "done",
  "result": {
    "zone_ids": ["uuid-1", "uuid-2"],
    "site_summary": "A music blog covering independent artists...",
    "audience_profile": {"age_range": "25-40", "interests": ["indie music", ...]},
    "estimated_monthly_revenue_usd": 120,
    "conversion_tips": ["Place native ads between article paragraphs", ...]
  }
}
```

### 3. Get your serve tags

```bash
curl http://localhost:8000/publishers/zones \
  -H "Authorization: Bearer <token>"
```

Returns all zones with pre-generated `serve_tag` HTML. Or fetch a single zone's tag:

```bash
curl http://localhost:8000/publishers/zones/<zone_id>/tag \
  -H "Authorization: Bearer <token>"
```

### 4. Add ads to your site

Add three snippets to your HTML:

**Step 1 — Paste once in `<head>` (before any other scripts):**

```html
<script>
  window._aias = window._aias || {
    q: [],
    push: function(c) { this.q.push(c); }
  };
</script>
```

**Step 2 — Place ad slot divs wherever you want ads to appear:**

For a banner (above the fold, full width):
```html
<div id="aias-YOUR-ZONE-UUID"></div>
```

For a native ad (in-content or sidebar):
```html
<div id="aias-YOUR-ZONE-UUID"></div>
```

If you want two placements of the same zone on one page, give the second one a custom `id`:
```html
<div id="aias-YOUR-ZONE-UUID-sidebar"></div>
```

**Step 3 — Load the script and push your zone configs (before `</body>`):**

```html
<script src="https://your-adserver.com/serve/serve.js" async></script>
<script>
  var BASE = 'https://your-adserver.com';

  // Banner zone
  window._aias.push({
    zone: 'YOUR-BANNER-ZONE-UUID',
    type: 'banner',
    base: BASE
  });

  // Native zone (in-content)
  window._aias.push({
    zone: 'YOUR-NATIVE-ZONE-UUID',
    type: 'native',
    base: BASE
  });

  // Same native zone, second placement (sidebar) — pass containerId
  window._aias.push({
    zone: 'YOUR-NATIVE-ZONE-UUID',
    type: 'native',
    base: BASE,
    containerId: 'aias-YOUR-NATIVE-ZONE-UUID-sidebar'
  });
</script>
```

#### Zone types

| `type`   | Creative format         | Typical placement               |
|----------|-------------------------|---------------------------------|
| `banner` | Dark card, landscape image + headline + CTA button | Above the fold, between sections |
| `native` | Small image + headline + body, card style | In-content, sidebar              |

#### How it works at runtime

1. `serve.js` loads async — doesn't block page render
2. It processes the `window._aias` queue
3. For each slot, it calls `GET /serve/{zone_id}?url=<encoded-page-url>`
4. The server runs a second-price RTB auction, picks the best-matching campaign, records an impression
5. The winning creative JSON is returned and rendered into the slot div
6. The ad's link points to `/auction/click/{impression_id}` — clicking records the click then redirects to the advertiser's product URL
7. If no campaigns match (no-fill), the slot stays empty and no impression is recorded

#### Demo page

`static/demo.html` is a working example showing a banner + two native placements on a fake music blog. Run the server and open it in a browser to see live ads.

---

## Click tracking

Every ad impression creates an `Impression` row. Clicks are tracked automatically via the redirect URL baked into each rendered ad.

To query impression and click data directly:

```sql
-- Impressions and CTR by campaign
SELECT
  c.brand_name,
  COUNT(*) AS impressions,
  SUM(CASE WHEN i.clicked THEN 1 ELSE 0 END) AS clicks,
  ROUND(100.0 * SUM(CASE WHEN i.clicked THEN 1 ELSE 0 END) / COUNT(*), 2) AS ctr_pct,
  ROUND(SUM(i.cpm_paid) / 1000, 4) AS spend_usd
FROM impressions i
JOIN campaigns c ON c.id = i.campaign_id
GROUP BY c.brand_name;
```

---

## Admin UI

A dev-only admin interface is available at **`http://localhost:8000/admin`** — no login required.

| Tab | What you can do |
|-----|-----------------|
| **Campaigns** | See all campaigns with live impression, click, CTR, and spend stats. Play/pause a campaign. Open a drawer showing all 3 creative variants with DALL-E images, copy, visual concepts, target audience, and value propositions. |
| **Advertisers** | See all advertiser accounts with current balance. Set balance to any amount inline for testing. |
| **Zones** | See all publisher inventory zones with impression and revenue stats. View the ready-to-paste serve tag for any zone. |
| **Impressions** | Last 50 impressions with brand, zone, CPM paid, click status, and page URL. |

---

## API reference

Interactive docs available at `http://localhost:8000/docs` (Swagger UI).

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/auth/register` | — | Register advertiser or publisher |
| POST | `/auth/login` | — | Get JWT token |
| POST | `/campaigns/create` | advertiser | Enqueue AI campaign creation |
| GET | `/campaigns` | advertiser | List your campaigns |
| GET | `/campaigns/{id}` | advertiser | Get one campaign |
| GET | `/jobs/{job_id}` | — | Poll background job status |
| POST | `/publishers/analyze-site` | publisher | Enqueue site analysis |
| GET | `/publishers/zones` | publisher | List your ad zones |
| GET | `/publishers/zones/{id}/tag` | publisher | Get serve tag for a zone |
| GET | `/serve/serve.js` | — | Publisher tag script |
| GET | `/serve/{zone_id}` | — | Run auction, return winning creative |
| GET | `/auction/click/{impression_id}` | — | Record click and redirect |
| GET | `/admin` | — | Admin UI (dev only) |
| GET | `/admin/api/campaigns` | — | All campaigns with stats |
| POST | `/admin/api/campaigns/{id}/status` | — | Pause or activate a campaign |
| GET | `/admin/api/advertisers` | — | All advertiser accounts |
| POST | `/admin/api/advertisers/{id}/balance` | — | Set advertiser balance |
| GET | `/admin/api/zones` | — | All inventory zones with stats |
| GET | `/admin/api/impressions` | — | Recent impressions |

---

## What's not built yet

- **Frequency capping** — no per-user impression limits; same visitor can see the same ad every page load (#13)
- **Budget pacing** — daily budgets are hard-capped but not spread evenly through the day (#14)
- **Bot filtering** — crawler traffic records impressions and burns advertiser budget (#15)
- **Conversion tracking** — clicks are tracked but not downstream events (signups, purchases) (#16)
- **Publisher earnings** — revenue split logic not implemented; publishers don't have a balance yet
- **Instagram integration** — `/publishers/instagram/monetize` endpoint exists but the full zone creation flow isn't wired to it
