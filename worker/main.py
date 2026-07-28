import json
import logging
import os
import time

import redis

from worker.pipeline import run_pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s")
logger = logging.getLogger("worker.run")

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
CLAIM_QUEUE_NAME = os.getenv("CLAIM_QUEUE_NAME", "claims:incoming")


def get_redis_client() -> redis.Redis:
    while True:
        try:
            # socket_timeout=None ekleyerek BRPOP beklemesinde soketin düşmesini engelliyoruz
            client = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                db=0,
                decode_responses=True,
                socket_timeout=None,
                socket_keepalive=True,
            )
            client.ping()
            logger.info(f"Successfully connected to Redis at {REDIS_HOST}:{REDIS_PORT}")
            return client
        except redis.ConnectionError:
            logger.warning(
                f"Waiting for Redis at {REDIS_HOST}:{REDIS_PORT}... Retrying in 3 seconds."
            )
            time.sleep(3)


def main():
    logger.info("Starting Claims Cockpit Worker (S1-5 State Machine Engine)...")
    redis_client = get_redis_client()
    logger.info(f"Listening for incoming claims on queue '{CLAIM_QUEUE_NAME}' using BRPOP...")

    while True:
        try:
            queue_name, message_data = redis_client.brpop(CLAIM_QUEUE_NAME, timeout=0)
            logger.info(f"Received new message from queue: {queue_name}")

            try:
                claim_data = json.loads(message_data)
            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error, marking message as dead_letter. Error: {str(e)}")
                continue

            processed_claim = run_pipeline(claim_data)
            msg_id = processed_claim.get("id", processed_claim.get("external_ref"))
            logger.info(
                f"Processing completed | message_id: {msg_id} | "
                f"Final Status: {processed_claim.get('status')}"
            )

        except redis.ConnectionError:
            logger.error("Lost connection to Redis. Attempting to reconnect...")
            redis_client = get_redis_client()
        except Exception as e:
            logger.error(f"Unexpected error in worker main loop: {str(e)}", exc_info=True)
            time.sleep(1)


if __name__ == "__main__":
    main()
