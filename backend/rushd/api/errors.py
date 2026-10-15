from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("rushd.api")


class ApiError(Exception):
    """An error whose Arabic message is safe to show to the user."""

    def __init__(self, status: int, message: str, code: str | None = None, headers: dict | None = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code
        self.headers = headers


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, exc: ApiError):
        body = {"detail": exc.message}
        if exc.code:
            body["code"] = exc.code
        return JSONResponse(body, status_code=exc.status, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_request: Request, exc: RequestValidationError):
        fields = []
        for err in exc.errors()[:10]:
            loc = ".".join(str(p) for p in err.get("loc", ()) if p not in ("body", "query", "path"))
            fields.append(loc)
        return JSONResponse({"detail": "البيانات المرسلة غير صالحة", "fields": fields}, status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_request: Request, exc: StarletteHTTPException):
        messages = {404: "غير موجود", 405: "طريقة غير مسموحة", 401: "غير مصرح"}
        detail = (
            exc.detail
            if isinstance(exc.detail, str) and not exc.detail.isascii()
            else messages.get(exc.status_code, "خطأ")
        )
        return JSONResponse({"detail": detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None))

    @app.exception_handler(Exception)
    async def _unexpected(_request: Request, exc: Exception):  # never leak stack traces
        log.exception("unhandled error", exc_info=exc)
        return JSONResponse({"detail": "حدث خطأ غير متوقع في الخادم"}, status_code=500)
