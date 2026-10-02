"""
IBM Cloud Terraform DriftGuard AI — Application entry point.

Starts the FastAPI application and configures logging.
"""
from __future__ import annotations

import contextlib
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config.logging import configure_logging, get_logger
from app.config.settings import get_settings

settings = get_settings()


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:  # noqa: ARG001
    """Application lifespan: startup and shutdown hooks."""
    configure_logging()
    logger = get_logger("main")
    logger.info(
        "DriftGuard AI starting",
        version=settings.app_version,
        environment=settings.environment,
        terraform_dir=settings.terraform_working_dir,
        llm_provider=settings.llm_provider,
        slack_enabled=settings.slack_enabled,
    )

    # Start the periodic drift detection scheduler.
    # Import deferred to avoid circular imports at module load time.
    from app.scheduler.scheduler import DriftScheduler  # noqa: PLC0415

    scheduler = DriftScheduler()
    scheduler.start()

    yield

    scheduler.stop()
    logger.info("DriftGuard AI stopped")


def create_app() -> FastAPI:
    """Factory function — creates and configures the FastAPI application."""
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "Detects Terraform infrastructure drift on IBM Cloud, "
            "analyzes changes with an AI agent, and sends Slack notifications."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # CORS — restrict to localhost for local development.
    # Override via environment for production deployments.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    app.include_router(router)
    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    configure_logging()
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.api_reload,
        log_config=None,  # Use structlog instead of uvicorn's default logging
    )
