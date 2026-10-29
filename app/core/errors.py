"""Application errors and the consistent JSON error format: {"error": {code, message, details}}."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("gymtrack")


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, code: str | None = None, details=None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        self.details = details


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Unauthenticated(AppError):
    status_code = 401
    code = "unauthenticated"


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_error"


class TooManyRequests(AppError):
    status_code = 429
    code = "too_many_requests"


def _body(code: str, message: str, details=None) -> dict:
    return {"error": {"code": code, "message": message, "details": details}}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_request: Request, exc: AppError):
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        return JSONResponse(
            _body(exc.code, exc.message, exc.details), status_code=exc.status_code, headers=headers
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError):
        details = [
            {"field": ".".join(str(p) for p in err["loc"] if p != "body"), "message": err["msg"]}
            for err in exc.errors()
        ]
        return JSONResponse(
            _body("validation_error", "Request validation failed", details), status_code=422
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_request: Request, exc: StarletteHTTPException):
        code = "not_found" if exc.status_code == 404 else "http_error"
        return JSONResponse(_body(code, str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception):
        # Log the traceback server-side only; never return internals to the client.
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            _body("internal_error", "An unexpected error occurred"), status_code=500
        )
