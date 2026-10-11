from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from blue_data_user_source import LLMError, UserExistsError, UserNotFoundError

from blue_data_user_api.config import settings
from blue_data_user_api.routes import contacts, data, databases, interactions, metadata, query, sessions
from blue_data_user_api.source import create_source

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    data_dir = settings.data_dir.expanduser().resolve()
    data_dir.mkdir(parents=True, exist_ok=True)

    source = create_source(
        data_dir,
        settings.schema_path,
        settings.metadata_schema_path,
        settings.contact_schema_path,
    )
    app.state.source = source
    app.state.data_dir = data_dir

    logger.info("UserSource initialised at %s", data_dir)
    yield
    logger.info("UserSource shutting down")


app = FastAPI(
    title="Blue Data User API",
    description="REST API for managing user data sources, querying, metadata, and contacts.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(databases.router)
app.include_router(query.router)
app.include_router(data.router)
app.include_router(metadata.router)
app.include_router(contacts.router)
app.include_router(interactions.router)
app.include_router(sessions.router)


_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


@app.middleware("http")
async def reject_cross_origin_writes(request: Request, call_next):  # type: ignore[no-untyped-def]
    """Refuse state-changing requests that a browser sends on behalf of another site (#139).

    A page on any site can make the browser POST to this API — a plain HTML
    form needs no CORS preflight — so with the default local setup (no API
    key) any page the operator visits could reset a user. Browsers attach an
    ``Origin`` header to such requests; scripts and SDKs send none. A write is
    allowed when it has no ``Origin`` (not a browser), or when the origin is
    this server's own or listed in ``BLUE_DATA_USER_SOURCE_ALLOWED_ORIGINS``.
    ``Origin: null`` (sandboxed or opaque contexts) is refused.
    """
    origin = request.headers.get("origin")
    if request.method in _WRITE_METHODS and origin is not None:
        own = f"{request.url.scheme}://{request.url.netloc}"
        allowed = {own, *(o.strip().rstrip("/") for o in settings.allowed_origins.split(",") if o.strip())}
        if origin.rstrip("/") not in allowed:
            return JSONResponse(
                status_code=403,
                content={"detail": f"Cross-origin {request.method} from {origin!r} refused; "
                                   "set BLUE_DATA_USER_SOURCE_ALLOWED_ORIGINS to allow it."},
            )
    return await call_next(request)


@app.exception_handler(UserNotFoundError)
async def user_not_found(request: Request, exc: UserNotFoundError) -> JSONResponse:
    """Any route naming a user that does not exist (#145)."""
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(UserExistsError)
async def user_exists(request: Request, exc: UserExistsError) -> JSONResponse:
    """Creating a user that already exists (#141)."""
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(LLMError)
async def llm_error(request: Request, exc: LLMError) -> JSONResponse:
    """The model behind a query could not answer: an upstream failure, not ours (#117)."""
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.get("/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok"}


def main() -> None:
    uvicorn.run(
        "blue_data_user_api.app:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
