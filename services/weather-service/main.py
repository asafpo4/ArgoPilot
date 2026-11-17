"""The weather-service HTTP app. Run with: uv run uvicorn main:app --host 127.0.0.1 --port 8001 --workers 1"""

from fastapi import FastAPI

from errors import install_handlers


def create_app() -> FastAPI:
    app = FastAPI(title="AgroPilot weather-service", version="0.1.0")
    install_handlers(app)

    @app.get("/health")
    def health() -> dict[str, str]:
        # Never calls the provider and never reads the cache.
        return {"status": "ok"}

    return app


app = create_app()
