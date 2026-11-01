from fastapi import FastAPI

from catalogues import router as catalogues_router

app = FastAPI(title="AgroPilot registry-service", version="0.1.0")
app.include_router(catalogues_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
