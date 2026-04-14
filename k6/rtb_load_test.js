/**
 * k6 RTB Load Test — AI Ad Server
 *
 * Simulates the real-time bidding pipeline end-to-end:
 *   1. setup()  — register advertiser + publisher, kick off AI campaign/zone
 *                 creation (or reuse pre-seeded IDs from env vars)
 *   2. Scenario A: high-volume auction bids via POST /auction/bid
 *   3. Scenario B: publisher serve-tag GET /serve/{zone_id}
 *   4. Scenario C: click-through redirects GET /auction/click/{impression_id}
 *
 * --- Quick start ---
 *   k6 run k6/rtb_load_test.js
 *
 * --- Skip AI setup (pre-seeded DB) ---
 *   ZONE_ID=<uuid> k6 run k6/rtb_load_test.js
 *
 * --- Environment variables ---
 *   BASE_URL          Server base URL (default: http://localhost:8000)
 *   ZONE_ID           Comma-separated zone UUIDs to use (skips setup registration)
 *   ADV_EMAIL         Advertiser email for login (used if ZONE_ID is supplied)
 *   ADV_PASSWORD      Advertiser password
 *   PUB_EMAIL         Publisher email for login
 *   PUB_PASSWORD      Publisher password
 *   AUCTION_VUS       VUs for auction scenario  (default: 20)
 *   SERVE_VUS         VUs for serve scenario    (default: 10)
 *   CLICK_VUS         VUs for click scenario    (default: 5)
 *   DURATION          Duration for each scenario (default: 30s)
 *   JOB_POLL_TIMEOUT  Max seconds to wait for AI jobs (default: 120)
 */

import http from "k6/http";
import { check, sleep, fail } from "k6";
import { Rate, Trend, Counter } from "k6/metrics";
import { SharedArray } from "k6/data";
import { randomItem } from "https://jslib.k6.io/k6-utils/1.4.0/index.js";

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const JOB_POLL_TIMEOUT = parseInt(__ENV.JOB_POLL_TIMEOUT || "120", 10);

const AUCTION_VUS = parseInt(__ENV.AUCTION_VUS || "20", 10);
const SERVE_VUS   = parseInt(__ENV.SERVE_VUS   || "10", 10);
const CLICK_VUS   = parseInt(__ENV.CLICK_VUS   || "5",  10);
const DURATION    = __ENV.DURATION || "30s";

// ---------------------------------------------------------------------------
// Custom metrics
// ---------------------------------------------------------------------------

const auctionDuration  = new Trend("rtb_auction_duration_ms",  true);
const noFillRate       = new Rate("rtb_no_fill_rate");
const clickRate        = new Rate("rtb_click_rate");
const auctionErrors    = new Counter("rtb_auction_errors");
const impressionsServed = new Counter("rtb_impressions_served");

// ---------------------------------------------------------------------------
// Realistic user-agent pool
// ---------------------------------------------------------------------------

const USER_AGENTS = [
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
  "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
  "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
];

// Simulated publisher page URLs
const PAGE_URLS = [
  "https://example-publisher.com/",
  "https://example-publisher.com/articles/tech-review",
  "https://example-publisher.com/articles/gadgets",
  "https://blog.example-pub.com/posts/ai-tools",
  "https://news.example-pub.com/sports/",
  "https://deals.example-pub.com/",
];

// ---------------------------------------------------------------------------
// k6 scenario configuration
// ---------------------------------------------------------------------------

export const options = {
  setupTimeout: "300s",  // AI campaign + site analysis jobs can take 1-2 min each
  scenarios: {
    // Core RTB path — POST /auction/bid
    auction_bids: {
      executor: "constant-vus",
      vus: AUCTION_VUS,
      duration: DURATION,
      exec: "auctionScenario",
      tags: { scenario: "auction" },
    },
    // Publisher tag — GET /serve/{zone_id}
    serve_tag: {
      executor: "constant-vus",
      vus: SERVE_VUS,
      duration: DURATION,
      exec: "serveScenario",
      tags: { scenario: "serve" },
      startTime: "2s",  // slight offset to let auction data populate
    },
    // Click-through tracking — GET /auction/click/{impression_id}
    click_tracking: {
      executor: "constant-vus",
      vus: CLICK_VUS,
      duration: DURATION,
      exec: "clickScenario",
      tags: { scenario: "click" },
      startTime: "5s",
    },
  },

  thresholds: {
    // Auction P95 must be under 100ms (RTB SLO)
    rtb_auction_duration_ms: ["p(95)<100", "p(99)<250"],
    // No more than 5% of auctions should fail with server errors (204 no-fill is acceptable)
    rtb_auction_errors: [{ threshold: "count<50", abortOnFail: false }],
    // Overall HTTP failure rate
    http_req_failed: ["rate<0.02"],
    // Auction endpoint specifically
    "http_req_duration{scenario:auction}": ["p(95)<100"],
  },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function authHeaders(token) {
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${token}`,
  };
}

function jsonPost(url, body, headers = { "Content-Type": "application/json" }) {
  return http.post(url, JSON.stringify(body), { headers });
}

/**
 * Register a user and return their JWT token.
 * Returns null on failure (e.g. email already registered — try login instead).
 */
function registerUser(email, password, role, extra = {}) {
  const res = jsonPost(`${BASE_URL}/auth/register`, {
    email,
    password,
    role,
    ...extra,
  });
  if (res.status === 201) {
    return JSON.parse(res.body).access_token;
  }
  // 409 = already registered, fall through to login
  return null;
}

function loginUser(email, password) {
  const res = http.post(
    `${BASE_URL}/auth/login`,
    `username=${encodeURIComponent(email)}&password=${encodeURIComponent(password)}`,
    { headers: { "Content-Type": "application/x-www-form-urlencoded" } }
  );
  if (res.status !== 200) {
    console.error(`Login failed for ${email}: ${res.status} ${res.body}`);
    return null;
  }
  return JSON.parse(res.body).access_token;
}

/**
 * Register then fall back to login, returning a JWT token.
 */
function getToken(email, password, role, extra = {}) {
  const token = registerUser(email, password, role, extra);
  if (token) return token;
  return loginUser(email, password);
}

/**
 * Poll GET /jobs/{job_id} until status is done or failed, or timeout expires.
 * Returns the job result object, or null on timeout/failure.
 */
function pollJob(jobId, timeoutSec = JOB_POLL_TIMEOUT) {
  const deadline = Date.now() + timeoutSec * 1000;
  while (Date.now() < deadline) {
    const res = http.get(`${BASE_URL}/jobs/${jobId}`);
    if (res.status !== 200) {
      console.error(`Job poll error ${res.status} for job ${jobId}`);
      sleep(2);
      continue;
    }
    const job = JSON.parse(res.body);
    if (job.status === "done") return job.result;
    if (job.status === "failed") {
      console.error(`Job ${jobId} failed: ${job.error}`);
      return null;
    }
    sleep(3);
  }
  console.error(`Job ${jobId} timed out after ${timeoutSec}s`);
  return null;
}

// ---------------------------------------------------------------------------
// setup() — runs once, creates test fixtures shared across all VUs
// ---------------------------------------------------------------------------

export function setup() {
  // If zone IDs were pre-seeded, skip the full registration + AI setup
  if (__ENV.ZONE_ID) {
    const zoneIds = __ENV.ZONE_ID.split(",").map((s) => s.trim()).filter(Boolean);
    console.log(`Using pre-seeded zone IDs: ${zoneIds.join(", ")}`);
    return { zoneIds, impressionIds: [] };
  }

  const ts = Date.now();
  const password = "LoadTest$ecure1!";

  // Two advertisers, one per product
  const advertisers = [
    { email: `loadtest-adv-bambu-${ts}@example.com`,   product_url: "https://us.store.bambulab.com/products/p1s",                              daily_budget: 100, total_budget: 500 },
    { email: `loadtest-adv-bantam-${ts}@example.com`,  product_url: "https://bantamtools.com/products/bantam-tools-artframe-1824",             daily_budget: 100, total_budget: 500 },
  ];

  // Two publishers, one per site
  const publishers = [
    { email: `loadtest-pub-wiki-${ts}@example.com`,    site_url: "https://en.wikipedia.org/wiki/Artificial_intelligence" },
    { email: `loadtest-pub-github-${ts}@example.com`,  site_url: "https://github.com/dnewcome/ai-adserver" },
  ];

  // --- Register advertisers and kick off campaign creation ---
  const campaignJobs = [];
  for (const adv of advertisers) {
    console.log(`--- setup: registering advertiser ${adv.email} ---`);
    const token = getToken(adv.email, password, "advertiser", { company_name: "k6 Load Test Co" });
    if (!token) { console.error(`Could not get token for ${adv.email}`); continue; }
    adv.token = token;

    // Resolve advertiser ID and fund the account
    const admRes = http.get(`${BASE_URL}/admin/api/advertisers`);
    if (admRes.status === 200) {
      const me = JSON.parse(admRes.body).find((a) => a.email === adv.email);
      if (me) {
        adv.id = me.id;
        jsonPost(`${BASE_URL}/admin/api/advertisers/${me.id}/balance`, { balance_usd: 500.0 });
        console.log(`Funded advertiser ${adv.email} ($500)`);
      }
    }

    console.log(`--- setup: creating campaign for ${adv.product_url} ---`);
    const res = jsonPost(
      `${BASE_URL}/campaigns/create`,
      { product_url: adv.product_url, daily_budget_usd: adv.daily_budget, total_budget_usd: adv.total_budget },
      authHeaders(token)
    );
    if (res.status === 202) {
      const job = JSON.parse(res.body);
      console.log(`Campaign job queued: ${job.job_id} (${adv.product_url})`);
      campaignJobs.push({ job_id: job.job_id, adv });
    } else {
      console.error(`Campaign creation failed for ${adv.product_url}: ${res.status} ${res.body}`);
    }
  }

  // --- Register publishers and kick off site analysis ---
  const analyzeJobs = [];
  for (const pub of publishers) {
    console.log(`--- setup: registering publisher ${pub.email} ---`);
    const token = getToken(pub.email, password, "publisher", { site_url: pub.site_url });
    if (!token) { console.error(`Could not get token for ${pub.email}`); continue; }
    pub.token = token;

    console.log(`--- setup: analyzing site ${pub.site_url} ---`);
    const res = jsonPost(
      `${BASE_URL}/publishers/analyze-site`,
      { site_url: pub.site_url },
      authHeaders(token)
    );
    if (res.status === 202) {
      const job = JSON.parse(res.body);
      console.log(`Site analysis job queued: ${job.job_id} (${pub.site_url})`);
      analyzeJobs.push({ job_id: job.job_id, pub });
    } else {
      console.error(`Site analysis failed for ${pub.site_url}: ${res.status} ${res.body}`);
    }
  }

  // --- Poll all jobs in parallel (sequentially here, but fast enough at 2 jobs each) ---
  console.log("--- setup: waiting for campaign jobs ---");
  for (const { job_id, adv } of campaignJobs) {
    const result = pollJob(job_id);
    if (result && result.campaign_id) {
      adv.campaign_id = result.campaign_id;
      console.log(`Campaign ready: ${result.campaign_id} (${adv.product_url})`);
      jsonPost(`${BASE_URL}/admin/api/campaigns/${result.campaign_id}/status`, { status: "ACTIVE" });
    } else {
      console.error(`Campaign job ${job_id} did not produce a campaign_id`);
    }
  }

  console.log("--- setup: waiting for site analysis jobs ---");
  let zoneIds = [];
  for (const { job_id, pub } of analyzeJobs) {
    const result = pollJob(job_id);
    if (result && result.zone_ids && result.zone_ids.length > 0) {
      console.log(`Zones ready for ${pub.site_url}: ${result.zone_ids.join(", ")}`);
      zoneIds = zoneIds.concat(result.zone_ids);
    } else {
      // Fallback: fetch zones directly from the publisher account
      const zonesRes = http.get(`${BASE_URL}/publishers/zones`, { headers: authHeaders(pub.token) });
      if (zonesRes.status === 200) {
        const ids = JSON.parse(zonesRes.body).map((z) => z.id);
        console.log(`Fetched ${ids.length} zones for ${pub.site_url} via fallback`);
        zoneIds = zoneIds.concat(ids);
      }
    }
  }

  if (zoneIds.length === 0) {
    console.warn("No inventory zones found — all auction calls will be 204 no-fill.");
  } else {
    console.log(`Setup complete. ${zoneIds.length} zone(s) available: ${zoneIds.join(", ")}`);
  }

  return {
    zoneIds,
    impressionIds: [],
  };
}

// ---------------------------------------------------------------------------
// Scenario A: Auction bids  (POST /auction/bid)
// ---------------------------------------------------------------------------

export function auctionScenario(data) {
  if (!data || data.zoneIds.length === 0) {
    // No zones — nothing to bid on; record as no-fill and pace
    noFillRate.add(1);
    sleep(1);
    return;
  }

  const zoneId   = randomItem(data.zoneIds);
  const pageUrl  = randomItem(PAGE_URLS);
  const ua       = randomItem(USER_AGENTS);

  const start = Date.now();
  const res = http.post(
    `${BASE_URL}/auction/bid`,
    JSON.stringify({ zone_id: zoneId, page_url: pageUrl }),
    {
      headers: {
        "Content-Type": "application/json",
        "User-Agent": ua,
      },
      tags: { endpoint: "auction_bid" },
    }
  );
  auctionDuration.add(Date.now() - start);

  const filled = res.status === 200;
  const noFill = res.status === 204;
  const errored = !filled && !noFill;

  check(res, {
    "auction: status is 200 or 204": (r) => r.status === 200 || r.status === 204,
    "auction: no 5xx errors":        (r) => r.status < 500,
  });

  noFillRate.add(noFill ? 1 : 0);

  if (errored) {
    auctionErrors.add(1);
    console.error(`Auction error: ${res.status} zone=${zoneId} body=${res.body.substring(0, 200)}`);
    sleep(1);
    return;
  }

  if (filled) {
    impressionsServed.add(1);
    const body = JSON.parse(res.body);
    check(body, {
      "auction: has impression_id": (b) => b.impression_id && b.impression_id.length > 0,
      "auction: has creative":      (b) => b.creative != null,
      "auction: cpm_paid > 0":      (b) => b.cpm_paid > 0,
      "auction: has click_url":     (b) => b.click_url && b.click_url.includes("/auction/click/"),
    });

    // Simulate ~5% click-through rate
    if (Math.random() < 0.05 && body.click_url) {
      const clickRes = http.get(body.click_url, {
        redirects: 0, // just record the redirect, don't follow
        tags: { endpoint: "click_tracking_inline" },
      });
      check(clickRes, {
        "inline click: 302 redirect": (r) => r.status === 302,
      });
      clickRate.add(1);
    } else {
      clickRate.add(0);
    }
  }

  // RTB think time: 100-500ms between ad slot loads
  sleep(Math.random() * 0.4 + 0.1);
}

// ---------------------------------------------------------------------------
// Scenario B: Serve tag  (GET /serve/{zone_id})
// ---------------------------------------------------------------------------

export function serveScenario(data) {
  if (!data || data.zoneIds.length === 0) {
    sleep(1);
    return;
  }

  const zoneId  = randomItem(data.zoneIds);
  const pageUrl = randomItem(PAGE_URLS);
  const ua      = randomItem(USER_AGENTS);

  const res = http.get(
    `${BASE_URL}/serve/${zoneId}?url=${encodeURIComponent(pageUrl)}`,
    {
      headers: { "User-Agent": ua },
      tags: { endpoint: "serve_tag" },
    }
  );

  check(res, {
    "serve: status is 200 or 204": (r) => r.status === 200 || r.status === 204,
    "serve: no 5xx":               (r) => r.status < 500,
  });

  if (res.status === 200) {
    const body = JSON.parse(res.body);
    check(body, {
      "serve: has impression_id": (b) => b.impression_id && b.impression_id.length > 0,
      "serve: has creative":      (b) => b.creative != null,
    });
  }

  sleep(Math.random() * 0.5 + 0.2);
}

// ---------------------------------------------------------------------------
// Scenario C: Click tracking  (GET /auction/click/{impression_id})
//
// Fetches recent impressions from the admin API and clicks through them to
// simulate a realistic CTR workload on the click-redirect endpoint.
// ---------------------------------------------------------------------------

// Cache of impression IDs fetched from the admin API, refreshed periodically
let _impressionCache = [];
let _lastFetch = 0;

function refreshImpressionCache() {
  const now = Date.now();
  if (now - _lastFetch < 10_000 && _impressionCache.length > 0) return; // cache 10s

  const res = http.get(`${BASE_URL}/admin/api/impressions?limit=100`, {
    tags: { endpoint: "admin_impressions" },
  });
  if (res.status === 200) {
    const impressions = JSON.parse(res.body);
    _impressionCache = impressions
      .filter((i) => !i.clicked) // only click un-clicked impressions
      .map((i) => i.id);
    _lastFetch = now;
  }
}

export function clickScenario(data) {
  refreshImpressionCache();

  if (_impressionCache.length === 0) {
    // No impressions yet — wait for auction VUs to generate some
    sleep(2);
    return;
  }

  const impressionId = randomItem(_impressionCache);

  const res = http.get(`${BASE_URL}/auction/click/${impressionId}`, {
    redirects: 0, // capture the 302 without following it
    tags: { endpoint: "click_redirect" },
  });

  check(res, {
    "click: is 302 redirect or 404": (r) => r.status === 302 || r.status === 404,
    "click: no 5xx":                 (r) => r.status < 500,
  });

  if (res.status === 302) {
    check(res, {
      "click: Location header present": (r) => r.headers["Location"] != null,
    });
  }

  sleep(Math.random() * 1 + 0.5);
}

// ---------------------------------------------------------------------------
// teardown() — summary reporting
// ---------------------------------------------------------------------------

export function teardown(data) {
  console.log("\n=== RTB Load Test Summary ===");
  console.log(`Zone IDs tested: ${data ? data.zoneIds.join(", ") || "(none)" : "(none)"}`);
  console.log(
    "Check k6 summary output for:\n" +
    "  rtb_auction_duration_ms  — P95/P99 auction latency\n" +
    "  rtb_no_fill_rate         — fraction of no-fill responses\n" +
    "  rtb_click_rate           — fraction of impressions that were clicked\n" +
    "  rtb_impressions_served   — total filled impressions\n" +
    "  rtb_auction_errors       — non-200/204 auction responses"
  );
}
