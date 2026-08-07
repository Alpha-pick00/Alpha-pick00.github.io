import httpx

from ..config import settings
from ..schemas import User

TOKEN_URL = "https://kauth.kakao.com/oauth/token"
USERINFO_URL = "https://kapi.kakao.com/v2/user/me"


async def exchange_code(code: str, redirect_uri: str) -> User:
    if not settings.kakao_client_id:
        raise RuntimeError("KAKAO_CLIENT_ID가 설정되지 않았습니다.")

    async with httpx.AsyncClient(timeout=15) as client:
        token_data = {
            "grant_type": "authorization_code",
            "client_id": settings.kakao_client_id,
            "redirect_uri": redirect_uri,
            "code": code,
        }
        if settings.kakao_client_secret:
            token_data["client_secret"] = settings.kakao_client_secret

        token_response = await client.post(
            TOKEN_URL,
            data=token_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        token_response.raise_for_status()
        access_token = token_response.json()["access_token"]

        userinfo_response = await client.get(
            USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        userinfo_response.raise_for_status()
        data = userinfo_response.json()

    account = data.get("kakao_account", {})
    profile = account.get("profile", {})

    return User(
        provider="kakao",
        provider_user_id=str(data["id"]),
        email=account.get("email"),
        name=profile.get("nickname"),
        picture=profile.get("profile_image_url"),
    )
