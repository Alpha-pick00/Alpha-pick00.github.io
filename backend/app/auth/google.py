import httpx

from ..schemas import User

USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


async def fetch_user(access_token: str) -> User:
    """프론트엔드에서 Google OAuth2 토큰 클라이언트(팝업)로 받은 access_token으로
    사용자 정보를 조회한다. ID 토큰 검증 대신 이 방식을 쓰는 이유는, Google의
    렌더링된 로그인 버튼(iframe)은 커스텀 스타일링이 안 되기 때문 — 팝업 플로우로
    바꾸면 카카오/네이버와 완전히 동일한 버튼 UI를 쓸 수 있다."""
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}
        )
        response.raise_for_status()
        data = response.json()

    return User(
        provider="google",
        provider_user_id=data["sub"],
        email=data.get("email"),
        name=data.get("name"),
        picture=data.get("picture"),
    )
