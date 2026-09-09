"""Authentication routes: signup, login, token refresh, current-user profile."""
from fastapi import APIRouter, status
from fastapi.security import OAuth2PasswordRequestForm
from typing import Annotated

from fastapi import Depends

from app.dependencies import CurrentUser, DbSession
from app.schemas import Token, TokenRefreshRequest, UserCreate, UserRead
from app.services import AuthService

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/signup", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def signup(payload: UserCreate, db: DbSession) -> UserRead:
    """Create a new user account."""
    user = await AuthService(db).signup(payload)
    return UserRead.model_validate(user)


@router.post("/login", response_model=Token)
async def login(
    db: DbSession,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> Token:
    """OAuth2-compatible token login. Use the `username` field for the email address.

    Swagger's "Authorize" button (and any standard OAuth2 client) posts here
    automatically as `application/x-www-form-urlencoded`.
    """
    return await AuthService(db).login(form_data.username, form_data.password)


@router.post("/refresh", response_model=Token)
async def refresh_token(payload: TokenRefreshRequest, db: DbSession) -> Token:
    """Exchange a valid refresh token for a fresh access/refresh token pair."""
    return await AuthService(db).refresh(payload.refresh_token)


@router.get("/me", response_model=UserRead)
async def read_current_user(current_user: CurrentUser) -> UserRead:
    """Return the authenticated user's profile."""
    return UserRead.model_validate(current_user)
