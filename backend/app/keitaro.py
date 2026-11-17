import httpx
from fastapi import HTTPException

from .config import settings


class Keitaro:
    def __init__(self):
        if not settings.keitaro_api_key:
            raise HTTPException(503, "KEITARO_API_KEY не настроен")
        self.client = httpx.AsyncClient(
            base_url=settings.keitaro_url.rstrip("/") + "/admin_api/v1/",
            headers={"Api-Key": settings.keitaro_api_key},
            timeout=20,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.client.aclose()

    async def request(self, method: str, path: str, **kwargs):
        try:
            response = await self.client.request(method, path.lstrip("/"), **kwargs)
        except httpx.RequestError as exc:
            raise HTTPException(502, f"Keitaro недоступен: {exc.__class__.__name__}") from exc
        if response.is_error:
            try:
                detail = response.json()
            except ValueError:
                detail = response.text[:300]
            raise HTTPException(response.status_code if response.status_code < 500 else 502, {"keitaro": detail})
        return response.json()

    async def get(self, path: str, **kwargs):
        return await self.request("GET", path, **kwargs)

    async def post(self, path: str, data: dict):
        return await self.request("POST", path, json=data)

    async def put(self, path: str, data: dict):
        return await self.request("PUT", path, json=data)
