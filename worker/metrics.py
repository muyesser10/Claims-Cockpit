# worker/metrics.py
"""Pipeline metrics for Prometheus (S3-9).

Exposed over HTTP by prometheus_client.start_http_server(9100), started in
worker/main.py — this is a plain metric-definition module, no server logic
here, same separation as api/metrics.py (definitions) vs api/main.py
(wiring).
"""

from prometheus_client import Counter, Gauge, Histogram

worker_messages_processed_total = Counter(
    "worker_messages_processed_total",
    "Messages process_message() completed without raising",
)

worker_messages_failed_total = Counter(
    "worker_messages_failed_total",
    "Messages process_message() raised an exception for",
)

worker_processing_duration_seconds = Histogram(
    "worker_processing_duration_seconds",
    "process_message() wall-clock duration",
)

worker_queue_depth = Gauge(
    "worker_queue_depth",
    "Pending message count on the Redis queue (LLEN claims:incoming), sampled each loop tick",
)
