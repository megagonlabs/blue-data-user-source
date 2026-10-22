from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from importlib.metadata import version as _version
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from blue_data_user_source import (
    ContactNotFoundError, InteractionError, LLMError, QueryError, SessionEndedError, SessionNotFoundError,
    UDbError, UserExistsError, UserNotFoundError,
)

from blue_data.server import resolve_bind

from blue_data_user_api.auth import DEFAULT_PORT, ENV_PREFIX
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
    version=_version("blue-data-user-api"),  # the installed package's, so it cannot drift (#116)
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
    key, when auth is disabled) any page the operator visits could reset a user. Browsers attach an
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


# Library errors become client errors instead of 500s (#140). Starlette picks
# the handler of the most specific class in the exception's MRO, so these
# subclasses win over the generic 422 below.
_STATUS: dict[type[Exception], int] = {
    UserNotFoundError: 404,      # #145
    SessionNotFoundError: 404,
    ContactNotFoundError: 404,
    UserExistsError: 409,        # #141
    SessionEndedError: 409,
    QueryError: 422,             # bad input to a query or a lookup
    InteractionError: 422,       # e.g. an unsupported contact protocol
    UDbError: 422,
}


async def _library_error(request: Request, exc: Exception) -> JSONResponse:
    status_code = next(_STATUS[cls] for cls in type(exc).__mro__ if cls in _STATUS)
    return JSONResponse(status_code=status_code, content={"detail": str(exc)})


for _cls in _STATUS:
    app.add_exception_handler(_cls, _library_error)


@app.exception_handler(LLMError)
async def llm_error(request: Request, exc: LLMError) -> JSONResponse:
    """The model behind a query could not answer: an upstream failure, not ours (#117)."""
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.get("/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok"}


def main() -> None:
    # Loopback and the family's port for this service unless BLUE_DATA_USER_API_HOST /
    # BLUE_DATA_USER_API_PORT say otherwise (#157).
    host, port = resolve_bind(ENV_PREFIX, default_port=DEFAULT_PORT)
    uvicorn.run("blue_data_user_api.app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
