"""Authentication service: registration, login, token refresh with rotation."""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, UnauthorizedError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.auth import RevokedRefreshToken
from app.models.compliance import ConsentRecord
from app.models.user import Role, User
from app.schemas.auth import LoginRequest, RegisterRequest


def register(db: Session, data: RegisterRequest) -> tuple[User, str, str]:
    """Create a new user account and return (user, access_token, refresh_token)."""
    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        raise ConflictError("Ya existe una cuenta con ese correo electrónico")

    user = User(
        email=data.email,
        full_name=data.full_name,
        hashed_password=hash_password(data.password),
        preferred_scale_max=5,
    )
    db.add(user)
    db.flush()  # Assigns user.id without committing

    # Assign default "worker" role
    worker_role = db.query(Role).filter(Role.name == "worker").first()
    if worker_role is None:
        worker_role = Role(name="worker", description="Standard worker role")
        db.add(worker_role)
        db.flush()
    user.roles.append(worker_role)

    # Create a default consent record (not granted until user accepts)
    consent = ConsentRecord(user_id=user.id, granted=False, scope="all", version="1.0")
    db.add(consent)

    db.commit()
    db.refresh(user)

    access = create_access_token(user.id, extra_claims={"email": user.email})
    refresh = create_refresh_token(
        user.id, extra_claims={"email": user.email, "tv": 0}
    )
    return user, access, refresh


def login(db: Session, data: LoginRequest) -> tuple[User, str, str]:
    """Authenticate a user and return (user, access_token, refresh_token)."""
    from app.core.config import settings

    user = db.query(User).filter(User.email == data.email).first()
    now = datetime.now(timezone.utc)
    if user and user.locked_until:
        locked_until = user.locked_until
        if locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=timezone.utc)
        if locked_until > now:
            raise UnauthorizedError(
                "Cuenta bloqueada temporalmente tras demasiados intentos fallidos"
            )
        user.failed_login_attempts = 0
        user.locked_until = None

    if not user or not verify_password(data.password, user.hashed_password):
        if user:
            user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
            if user.failed_login_attempts >= settings.LOGIN_MAX_FAILED_ATTEMPTS:
                user.locked_until = now + timedelta(
                    minutes=settings.LOGIN_LOCKOUT_MINUTES
                )
            db.commit()
        raise UnauthorizedError("Correo electrónico o contraseña incorrectos")
    if not user.is_active:
        raise UnauthorizedError("Cuenta inactiva")

    user.failed_login_attempts = 0
    user.locked_until = None
    db.commit()

    access = create_access_token(user.id, extra_claims={"email": user.email})
    refresh = create_refresh_token(
        user.id,
        extra_claims={"email": user.email, "tv": user.token_version or 0},
    )
    return user, access, refresh


def refresh_access_token(db: Session, refresh_token: str) -> tuple[User, str, str]:
    """Validate a refresh token, revoke it (single-use) and rotate.

    Returns (user, new_access_token, new_refresh_token). Reusing an
    already-rotated token is rejected.
    """
    payload = decode_token(refresh_token)
    if payload is None or payload.get("type") != "refresh":
        raise UnauthorizedError("Token de actualización inválido")

    jti = payload.get("jti")
    if not jti:
        raise UnauthorizedError("Token de actualización inválido")
    if db.query(RevokedRefreshToken).filter(RevokedRefreshToken.jti == jti).first():
        raise UnauthorizedError("Token de actualización ya utilizado")

    user_id = payload.get("sub")
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        raise UnauthorizedError("Token de actualización inválido")
    if payload.get("tv", 0) != (user.token_version or 0):
        raise UnauthorizedError("Token revocado (inicia sesión de nuevo)")

    exp = payload.get("exp")
    expires_at = None
    try:
        if isinstance(exp, (int, float)):
            expires_at = datetime.fromtimestamp(exp, tz=timezone.utc)
    except (ValueError, OSError):
        expires_at = None
    db.add(RevokedRefreshToken(jti=jti, user_id=user.id, expires_at=expires_at))

    # Opportunistic cleanup of long-expired revocations.
    try:
        db.query(RevokedRefreshToken).filter(
            RevokedRefreshToken.expires_at.is_not(None),
            RevokedRefreshToken.expires_at < datetime.now(timezone.utc),
        ).delete(synchronize_session=False)
    except Exception:
        pass

    access = create_access_token(user.id, extra_claims={"email": user.email})
    new_refresh = create_refresh_token(
        user.id,
        extra_claims={
            "email": user.email,
            "tv": user.token_version or 0,
        },
    )
    db.commit()
    return user, access, new_refresh


def logout(db: Session, refresh_token: str) -> bool:
    """Revoke a refresh token (logout on one device). Returns True if revoked."""
    from app.core.security import decode_token as _decode

    payload = _decode(refresh_token)
    if payload is None or payload.get("type") != "refresh" or not payload.get("jti"):
        return False
    jti = payload["jti"]
    if db.query(RevokedRefreshToken).filter(RevokedRefreshToken.jti == jti).first():
        return True
    exp = payload.get("exp")
    expires_at = None
    try:
        if isinstance(exp, (int, float)):
            expires_at = datetime.fromtimestamp(exp, tz=timezone.utc)
    except (ValueError, OSError):
        expires_at = None
    db.add(RevokedRefreshToken(
        jti=jti, user_id=str(payload.get("sub", "")), expires_at=expires_at
    ))
    db.commit()
    return True


def logout_all(db: Session, user: User) -> int:
    """Revoke all refresh tokens for a user by bumping the token version.

    All previously issued refresh tokens carry the old ``tv`` and are
    rejected on next use. Returns the new version.
    """
    user.token_version = (user.token_version or 0) + 1
    db.commit()
    return user.token_version
