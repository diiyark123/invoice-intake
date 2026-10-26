"""Password hashing, signed login tokens (D1) and role checks."""

import uuid
from dataclasses import dataclass
from typing import Annotated

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import get_settings

TOKEN_MAX_AGE_SECONDS = 8 * 60 * 60
_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    role: str


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def _serializer() -> URLSafeTimedSerializer:
    secret = get_settings().session_secret
    if not secret:
        raise RuntimeError("SESSION_SECRET is not set")
    return URLSafeTimedSerializer(secret, salt="login")


def create_token(user_id: uuid.UUID, role: str) -> str:
    return _serializer().dumps({"uid": str(user_id), "role": role})


def read_token(token: str, max_age: int = TOKEN_MAX_AGE_SECONDS) -> CurrentUser:
    try:
        data = _serializer().loads(token, max_age=max_age)
    except SignatureExpired as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired") from exc
    except BadSignature as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from exc
    return CurrentUser(id=uuid.UUID(data["uid"]), role=data["role"])


def require_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> CurrentUser:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not logged in")
    return read_token(creds.credentials)


def require_manager(user: Annotated[CurrentUser, Depends(require_user)]) -> CurrentUser:
    if user.role != "manager":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Manager only")
    return user
