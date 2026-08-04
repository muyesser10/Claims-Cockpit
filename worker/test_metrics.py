# worker/test_metrics.py
"""Unit tests for worker/metrics.py's metric definitions.

No real Redis connection or HTTP server here on purpose (start_http_server
binding a port and the BRPOP loop both need integration-level setup this
repo doesn't have yet) — just enough to prove the metrics are importable,
correctly typed, and can be incremented/observed/set without raising.
"""

from prometheus_client import generate_latest

from worker.metrics import (
    worker_messages_failed_total,
    worker_messages_processed_total,
    worker_processing_duration_seconds,
    worker_queue_depth,
)


def test_worker_metrics_can_be_recorded_without_raising():
    worker_messages_processed_total.inc()
    worker_messages_failed_total.inc()
    worker_processing_duration_seconds.observe(0.42)
    worker_queue_depth.set(3)


def test_worker_metrics_appear_in_exposition_output():
    """generate_latest() reads the default global registry — the same one
    prometheus_client.start_http_server() serves in the real worker."""
    output = generate_latest().decode()

    assert "worker_messages_processed_total" in output
    assert "worker_messages_failed_total" in output
    assert "worker_processing_duration_seconds" in output
    assert "worker_queue_depth" in output
