from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.exceptions import AppException
from app.core.logging import setup_logging
from app.core.responses import error_response

settings = get_settings()
setup_logging()


# Create the FastAPI application instance
app = FastAPI(
    title=settings.PROJECT_NAME,  # Title shown in the automatic docs
    openapi_url=f"{settings.API_V1_STR}/openapi.json",  # Path for the OpenAPI schema
)


@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    return JSONResponse(
        status_code=exc.status_code,
        content=error_response(message=exc.message, code=exc.code),
    )


# Simple root endpoint to check if the API is running
@app.get("/")
def root():
    return {
        "message": "Welcome to E-DEM Matching API",
        "docs": "/docs",  # Link to the interactive documentation
    }


# Health check endpoint (useful for monitoring and deployment)
@app.get("/health")
def health_check():
    return {"status": "ok"}
