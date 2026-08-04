import logging
import os
import time

import redis
from prometheus_client import start_http_server

from api.database import SessionLocal
from worker.metrics import (
    worker_messages_failed_total,
    worker_messages_processed_total,
    worker_processing_duration_seconds,
    worker_queue_depth,
)
from worker.pipeline import process_message

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
)
logger = logging.getLogger("worker.main")

REDIS_URL = os.environ["REDIS_URL"]  # Read from the same source as api/redis_client.py
QUEUE_KEY = "claims:incoming"
METRICS_PORT = 9100


def get_redis_client() -> redis.Redis:
    while True:
        try:
            client = redis.from_url(
                REDIS_URL,
                decode_responses=True,
                socket_timeout=10,
                socket_keepalive=True,
            )
            client.ping()
            logger.info(f"Connected to Redis at: {REDIS_URL}")
            return client
        except redis.ConnectionError:
            logger.warning("Waiting for Redis... Retrying in 3 seconds.")
            time.sleep(3)


def main():
    logger.info("Starting Worker (S1-5)...")
    start_http_server(METRICS_PORT)
    logger.info(f"Metrics server listening on :{METRICS_PORT}/metrics")
    r = get_redis_client()
    logger.info(f"Listening to queue '{QUEUE_KEY}'...")

    while True:
        try:
            # Cheap; sampled every tick so worker_queue_depth reflects
            # backlog even during a long BRPOP wait (up to the 5s timeout).
            worker_queue_depth.set(r.llen(QUEUE_KEY))

            item = r.brpop(QUEUE_KEY, timeout=5)
            if item is None:
                continue  # timeout

            _, raw_id_str = item
            try:
                raw_message_id = int(raw_id_str)
            except ValueError:
                logger.error(f"Invalid id received from queue: {raw_id_str!r}, skipping")
                continue

            db = SessionLocal()
            started = time.perf_counter()
            try:
                process_message(db, raw_message_id)
                worker_messages_processed_total.inc()
            except Exception:
                worker_messages_failed_total.inc()
                raise
            finally:
                worker_processing_duration_seconds.observe(time.perf_counter() - started)
                db.close()

        except redis.ConnectionError:
            logger.error("Lost connection to Redis, attempting to reconnect...")
            r = get_redis_client()
        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}", exc_info=True)
            time.sleep(1)


if __name__ == "__main__":
    main()
