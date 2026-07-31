from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import claims, ingest, queue

app = FastAPI(title="Claims-Cockpit API", version="0.1.1")

# CORS: allow the web app (5173) to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingest.router)
app.include_router(claims.router)
app.include_router(queue.router)


@app.get("/health")
def health():
    """Liveness check. DB + Redis checks will be added in later sprints."""
    return {"status": "ok", "service": "api"}
