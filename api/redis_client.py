# api/redis_client.py
import os

import redis

REDIS_URL = os.environ["REDIS_URL"]
r = redis.from_url(REDIS_URL, decode_responses=True)

QUEUE_KEY = "claims:incoming"


def enqueue_message(raw_message_id: int):
    """Push a raw message id onto the worker queue."""
    r.lpush(QUEUE_KEY, str(raw_message_id))
