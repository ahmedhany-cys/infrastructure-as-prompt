"""FastAPI application entry point."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import projects, workflow
from app.config import get_settings
from app.db import init_db
from app.services.operations import manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("iap")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    recovered = manager.recover_interrupted()
    if recovered:
        log.warning("Marked %d operation(s) as interrupted after restart", recovered)
    yield


app = FastAPI(
    title="Infrastructure as Prompt API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url=None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["content-type", "x-csrf-token"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    if request.url.path.startswith("/api/") and not request.url.path.startswith("/api/docs"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    # Echo field locations and messages, never the submitted values.
    errors = [{"loc": e.get("loc"), "msg": e.get("msg")} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": "Invalid request.", "errors": errors})


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception) -> JSONResponse:
    log.exception("Unhandled error: %s", type(exc).__name__)
    return JSONResponse(status_code=500, content={"detail": "Internal error. The incident was logged without request data."})


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(projects.router)
app.include_router(workflow.router)
