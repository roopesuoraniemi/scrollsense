"""Bearer-token check for the API, because a tunnel exposes the server (and the Gemini key)."""
import hmac
from typing import Annotated

from fastapi import Header, HTTPException


class BearerToken:
    """FastAPI dependency: raises 401 unless `Authorization: Bearer <token>` matches."""

    def __init__(self, token: str) -> None:
        self.__expected = f"Bearer {token}".encode()

    def __call__(self, authorization: Annotated[str | None, Header()] = None) -> None:
        offered = (authorization or "").encode()
        if not hmac.compare_digest(offered, self.__expected):
            raise HTTPException(401, "Missing or wrong bearer token",
                                headers={"WWW-Authenticate": "Bearer"})
