"""Centralized exception classes and handlers."""

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse


class AppException(HTTPException):
    """Base application exception with a stable error code."""

    def __init__(self, detail: str, status_code: int = status.HTTP_400_BAD_REQUEST, code: str = "error"):
        super().__init__(status_code=status_code, detail=detail)
        self.code = code


class NotFoundError(AppException):
    def __init__(self, detail: str = "Resource not found"):
        super().__init__(detail=detail, status_code=status.HTTP_404_NOT_FOUND, code="not_found")


class ConflictError(AppException):
    def __init__(self, detail: str = "Conflict"):
        super().__init__(detail=detail, status_code=status.HTTP_409_CONFLICT, code="conflict")


class ForbiddenError(AppException):
    def __init__(self, detail: str = "You don't have permission to do that"):
        super().__init__(detail=detail, status_code=status.HTTP_403_FORBIDDEN, code="forbidden")


class UnauthorizedError(AppException):
    def __init__(self, detail: str = "Authentication required"):
        super().__init__(detail=detail, status_code=status.HTTP_401_UNAUTHORIZED, code="unauthorized")


class ValidationError(AppException):
    def __init__(self, detail: str = "Validation failed"):
        super().__init__(detail=detail, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, code="validation_error")


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.code,
            "detail": exc.detail,
        },
    )
