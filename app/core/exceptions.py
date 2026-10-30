from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class ServiceUnavailableError(RuntimeError):
    pass


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ServiceUnavailableError)
    async def service_unavailable_handler(
        request: Request, exc: ServiceUnavailableError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "detail": "A required service is unavailable",
                "request_id": request.headers.get("X-Request-ID"),
            },
        )
