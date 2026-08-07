from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from ..config import settings
from ..schemas import User


def verify_id_token(credential: str) -> User:
    """Google Identity Services가 프론트엔드에 내려준 ID 토큰을 검증한다.
    audience가 우리 OAuth Client ID와 일치하는지까지 확인하므로, 다른 곳에서
    발급된 토큰을 재사용하는 위조 시도를 막는다."""
    if not settings.google_oauth_client_id:
        raise RuntimeError("GOOGLE_OAUTH_CLIENT_ID가 설정되지 않았습니다.")

    payload = id_token.verify_oauth2_token(
        credential, google_requests.Request(), settings.google_oauth_client_id
    )

    return User(
        provider="google",
        provider_user_id=payload["sub"],
        email=payload.get("email"),
        name=payload.get("name"),
        picture=payload.get("picture"),
    )
