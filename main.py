from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.campaigns import router as campaigns_router
from api.publishers import router as publishers_router

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

app.include_router(campaigns_router)
app.include_router(publishers_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
