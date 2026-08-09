import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from api.database import SessionLocal
from api.demo import is_demo_offline
from api.metrics import refresh_queue_metrics
from api.routers import auth, claims, ingest, quality, question, queue, stats

logger = logging.getLogger("api.main")

# How often the queue gauges (claims_in_human_review_total etc.) are
# recomputed. Not tied to Prometheus's own scrape_interval — this just has
# to be frequent enough that a scrape never sees stale-by-minutes data.
QUEUE_METRICS_REFRESH_SECONDS = 15


def _refresh_queue_metrics_loop(stop_event: threading.Event) -> None:
    """Background loop: recompute the queue gauges every
    QUEUE_METRICS_REFRESH_SECONDS.

    Opens its own DB session per tick with SessionLocal() directly (same
    pattern as worker/main.py's consumer loop) instead of get_db, which is
    a per-request FastAPI dependency and has no meaning outside a request.
    `stop_event.wait()` doubles as the sleep and a way to exit promptly on
    shutdown instead of blocking up to 15s.
    """
    while not stop_event.wait(QUEUE_METRICS_REFRESH_SECONDS):
        db = SessionLocal()
        try:
            refresh_queue_metrics(db)
        except Exception:
            logger.exception("refresh_queue_metrics failed")
        finally:
            db.close()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    stop_event = threading.Event()
    thread = threading.Thread(target=_refresh_queue_metrics_loop, args=(stop_event,), daemon=True)
    thread.start()
    yield
    stop_event.set()


app = FastAPI(title="Claims-Cockpit API", version="0.1.1", lifespan=lifespan)


# CORS: allow the web app (5173) to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(ingest.router)
app.include_router(claims.router)
app.include_router(queue.router)
app.include_router(stats.router)
app.include_router(quality.router)
# /soru is a proxy, not an implementation — the answer is produced by the rag
# service (ADR-003).
app.include_router(question.router)

# Auto HTTP metrics (request rate/latency/error rate) + exposes GET /metrics.
# No auth dependency here on purpose — Prometheus needs to scrape this
# unauthenticated, same reasoning as /health. When S3-8's JWT auth merges,
# /metrics (like /health) must stay off get_current_user.
Instrumentator().instrument(app).expose(app)


@app.get("/health")
def health():
    """Liveness check, deliberately unauthenticated (load balancers, docker
    healthcheck, etc. cannot carry a user JWT). DB + Redis checks will be
    added in later sprints.

    `demo_offline` is here rather than behind auth because that is where the
    cockpit can read it before anyone logs in, and because "are these answers
    recorded or live" is a question a demo audience is entitled to have
    answered without taking anyone's word for it (S4-6).
    """
    return {"status": "ok", "service": "api", "demo_offline": is_demo_offline()}
