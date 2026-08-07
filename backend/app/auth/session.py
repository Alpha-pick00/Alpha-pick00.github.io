from datetime import UTC, datetime, timedelta

import jwt

from ..config import settings
from ..schemas import User

ALGORITHM = "HS256"
SESSION_TTL = timedelta(days=30)


def issue_session_token(user: User) -> str:
    payload = {
        "provider": user.provider,
        "sub": user.provider_user_id,
        "email": user.email,
        "name": user.name,
        "picture": user.picture,
        "exp": datetime.now(UTC) + SESSION_TTL,
    }
    return jwt.encode(payload, settings.session_secret_key, algorithm=ALGORITHM)


def verify_session_token(token: str) -> User:
    payload = jwt.decode(token, settings.session_secret_key, algorithms=[ALGORITHM])
    return User(
        provider=payload["provider"],
        provider_user_id=payload["sub"],
        email=payload.get("email"),
        name=payload.get("name"),
        picture=payload.get("picture"),
    )
