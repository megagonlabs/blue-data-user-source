from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from blue_data_user_source import LLMError, UserNotFoundError

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


@app.exception_handler(UserNotFoundError)
async def user_not_found(request: Request, exc: UserNotFoundError) -> JSONResponse:
    """Any route naming a user that does not exist (#145)."""
    return JSONResponse(status_code=404, content={"detail": str(exc)})


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
