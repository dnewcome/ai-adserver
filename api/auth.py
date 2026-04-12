from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.advertiser import Advertiser
from models.base import get_db
from models.publisher import Publisher

router = APIRouter(prefix="/auth", tags=["auth"])

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    role: Literal["advertiser", "publisher"]
    company_name: str | None = None
    site_url: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hash(password: str) -> str:
    return pwd_context.hash(password)


def _verify(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def _create_token(subject: str, role: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)
    return jwt.encode(
        {"sub": subject, "role": role, "exp": expire},
        settings.secret_key,
        algorithm=settings.algorithm,
    )


def _decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ---------------------------------------------------------------------------
# Auth dependencies — import these in other routers
# ---------------------------------------------------------------------------

async def get_current_advertiser(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> Advertiser:
    payload = _decode_token(token)
    if payload.get("role") != "advertiser":
        raise HTTPException(status_code=403, detail="Advertiser access required")
    result = await db.execute(select(Advertiser).where(Advertiser.id == payload["sub"]))
    advertiser = result.scalar_one_or_none()
    if not advertiser:
        raise HTTPException(status_code=401, detail="Advertiser not found")
    return advertiser


async def get_current_publisher(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> Publisher:
    payload = _decode_token(token)
    if payload.get("role") != "publisher":
        raise HTTPException(status_code=403, detail="Publisher access required")
    result = await db.execute(select(Publisher).where(Publisher.id == payload["sub"]))
    publisher = result.scalar_one_or_none()
    if not publisher:
        raise HTTPException(status_code=401, detail="Publisher not found")
    return publisher


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Create an advertiser or publisher account and return a JWT."""
    hashed = _hash(req.password)

    if req.role == "advertiser":
        existing = await db.execute(select(Advertiser).where(Advertiser.email == req.email))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Email already registered")
        user = Advertiser(
            email=req.email,
            hashed_password=hashed,
            company_name=req.company_name,
            website=req.site_url,
        )
    else:
        existing = await db.execute(select(Publisher).where(Publisher.email == req.email))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Email already registered")
        user = Publisher(
            email=req.email,
            hashed_password=hashed,
            site_url=req.site_url,
        )

    db.add(user)
    await db.commit()
    await db.refresh(user)

    return TokenResponse(
        access_token=_create_token(user.id, req.role),
        role=req.role,
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    form: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """Exchange email + password for a JWT. Works for both advertisers and publishers."""
    # Try advertiser first, then publisher
    result = await db.execute(select(Advertiser).where(Advertiser.email == form.username))
    user = result.scalar_one_or_none()
    role = "advertiser"

    if not user:
        result = await db.execute(select(Publisher).where(Publisher.email == form.username))
        user = result.scalar_one_or_none()
        role = "publisher"

    if not user or not _verify(form.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return TokenResponse(
        access_token=_create_token(user.id, role),
        role=role,
    )
