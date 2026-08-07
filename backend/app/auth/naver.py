import httpx

from ..config import settings
from ..schemas import User

TOKEN_URL = "https://nid.naver.com/oauth2.0/token"
USERINFO_URL = "https://openapi.naver.com/v1/nid/me"


async def exchange_code(code: str, state: str | None) -> User:
    if not (settings.naver_client_id and settings.naver_client_secret):
        raise RuntimeError("NAVER_CLIENT_ID/NAVER_CLIENT_SECRET이 설정되지 않았습니다.")

    async with httpx.AsyncClient(timeout=15) as client:
        token_response = await client.get(
            TOKEN_URL,
            params={
                "grant_type": "authorization_code",
                "client_id": settings.naver_client_id,
                "client_secret": settings.naver_client_secret,
                "code": code,
                "state": state or "",
            },
        )
        token_response.raise_for_status()
        token_body = token_response.json()
        if "access_token" not in token_body:
            raise RuntimeError(token_body.get("error_description") or "네이버 토큰 발급에 실패했습니다.")
        access_token = token_body["access_token"]

        userinfo_response = await client.get(
            USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        userinfo_response.raise_for_status()
        data = userinfo_response.json()

    if data.get("resultcode") != "00":
        raise RuntimeError(data.get("message") or "네이버 사용자 정보 조회에 실패했습니다.")

    response = data.get("response", {})

    return User(
        provider="naver",
        provider_user_id=response["id"],
        email=response.get("email"),
        name=response.get("name") or response.get("nickname"),
        picture=response.get("profile_image"),
    )
