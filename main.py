from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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
        "analyze publisher inventory, and monetize social media accounts."
    ),
    version="0.1.0",
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


@app.get("/health")
async def health():
    return {"status": "ok"}
