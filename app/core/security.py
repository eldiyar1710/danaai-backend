from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any, Literal
from uuid import UUID, uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from pydantic import BaseModel

from app.core.config import Settings
from app.modules.users.models import UserRole

password_hasher = PasswordHasher()


class TokenClaims(BaseModel):
    sub: UUID
    jti: UUID
    type: Literal["access", "refresh"]
    role: UserRole
    organization_id: UUID | None = None
    iat: datetime
    exp: datetime


class TokenError(ValueError):
    pass


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_password_rehash(password_hash: str) -> bool:
    return password_hasher.check_needs_rehash(password_hash)


def hash_refresh_token(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def create_token(
    *,
    user_id: UUID,
    role: UserRole,
    organization_id: UUID | None,
    token_type: Literal["access", "refresh"],
    settings: Settings,
    jti: UUID | None = None,
) -> tuple[str, TokenClaims]:
    now = datetime.now(UTC)
    lifetime = (
        timedelta(minutes=settings.access_token_expire_minutes)
        if token_type == "access"
        else timedelta(days=settings.refresh_token_expire_days)
    )
    claims = TokenClaims(
        sub=user_id,
        jti=jti or uuid4(),
        type=token_type,
        role=role,
        organization_id=organization_id,
        iat=now,
        exp=now + lifetime,
    )
    payload: dict[str, Any] = {
        "sub": str(claims.sub),
        "jti": str(claims.jti),
        "type": claims.type,
        "role": claims.role.value,
        "organization_id": str(claims.organization_id) if claims.organization_id else None,
        "iat": int(claims.iat.timestamp()),
        "exp": int(claims.exp.timestamp()),
    }
    token = jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    return token, claims


def decode_token(token: str, settings: Settings, expected_type: str) -> TokenClaims:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "jti", "type", "role", "iat", "exp"]},
        )
        claims = TokenClaims.model_validate(payload)
    except (jwt.PyJWTError, ValueError) as exc:
        raise TokenError("Invalid or expired token") from exc
    if claims.type != expected_type:
        raise TokenError("Unexpected token type")
    return claims
