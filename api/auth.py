from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import JSONResponse

from config import settings


API_KEY_HEADER = "X-API-Key"


def _is_health_path(path: str) -> bool:

    return path.rstrip("/") == "/health"


def _configured_api_key() -> str:

    return (settings.API_KEY or "").strip()


def register_api_key_middleware(app: FastAPI) -> None:

    @app.middleware("http")
    async def verify_api_key(request: Request, call_next):

        configured = _configured_api_key()

        if not configured:

            return await call_next(request)

        if _is_health_path(request.url.path):

            return await call_next(request)

        provided = request.headers.get(API_KEY_HEADER)

        if provided != configured:

            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"},
            )

        return await call_next(request)
