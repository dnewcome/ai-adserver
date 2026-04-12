from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.admin import router as admin_router
from api.auction import router as auction_router
from api.auth import router as auth_router
from api.campaigns import router as campaigns_router
from api.jobs import router as jobs_router
from api.publishers import router as publishers_router
from api.serve import router as serve_router

app = FastAPI(
    title="AI Ad Server",
    description=(
        "Automatically generate ad campaigns from product URLs, "
        "analyze publisher inventory, and monetize social media accounts.\n\n"
        "## Authentication\n"
        "Most advertiser and publisher endpoints require a Bearer JWT.\n"
        "Call `POST /auth/register` then `POST /auth/login` to obtain a token,\n"
        "then pass it as `Authorization: Bearer <token>`.\n\n"
        "## Admin\n"
        "Endpoints under `/admin/api/` require no authentication and are "
        "intended for internal dev/ops use only.\n\n"
        "## Async jobs\n"
        "Long-running operations (campaign creation, site analysis) return a "
        "`job_id` immediately. Poll `GET /jobs/{job_id}` until `status` is "
        "`done` or `failed`."
    ),
    version="0.1.0",
    openapi_tags=[
        {"name": "auth",      "description": "Register and log in as advertiser or publisher."},
        {"name": "campaigns", "description": "Advertiser campaign management (JWT required)."},
        {"name": "publishers","description": "Publisher site analysis and zone management (JWT required)."},
        {"name": "auction",   "description": "RTB auction engine — bid and click-tracking endpoints."},
        {"name": "serve",     "description": "Publisher tag delivery (serve.js and per-zone ad endpoint)."},
        {"name": "jobs",      "description": "Poll background task status."},
        {"name": "admin",     "description": "No-auth admin API for internal use."},
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(admin_router)
app.include_router(auth_router)
app.include_router(campaigns_router)
app.include_router(publishers_router)
app.include_router(auction_router)
app.include_router(serve_router)
app.include_router(jobs_router)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/admin", include_in_schema=False)
async def admin_ui():
    return FileResponse("static/admin.html")


@app.get("/health", tags=["admin"])
async def health():
    """Liveness check."""
    return {"status": "ok"}


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        tags=app.openapi_tags,
        routes=app.routes,
    )
    schema.setdefault("components", {}).setdefault("securitySchemes", {})["BearerAuth"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
    }
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi
