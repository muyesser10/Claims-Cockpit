# worker/test_metrics.py
"""Unit tests for worker/metrics.py's metric definitions.

No real Redis connection or HTTP server here on purpose (start_http_server
binding a port and the BRPOP loop both need integration-level setup this
repo doesn't have yet) — just enough to prove the metrics are importable,
correctly typed, and can be incremented/observed/set without raising.
"""

from prometheus_client import generate_latest

from worker.metrics import (
    llm_calls_total,
    llm_tokens_total,
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


def test_llm_metrics_can_be_recorded_without_raising():
    """Both label sets, so a typo in a label name fails here and not in prod."""
    llm_tokens_total.labels(model="gpt-4o-mini", tier="cheap", kind="prompt").inc(120)
    llm_tokens_total.labels(model="gpt-4o-mini", tier="cheap", kind="completion").inc(8)
    llm_calls_total.labels(model="gpt-4o-mini", tier="cheap", outcome="ok").inc()
    llm_calls_total.labels(model="gpt-4o", tier="strong", outcome="error").inc()


def test_llm_metrics_appear_in_exposition_output():
    """These two are also exported by the rag service, which loads the same
    worker/llm/client.py into the same global registry."""
    output = generate_latest().decode()

    assert "llm_tokens_total" in output
    assert "llm_calls_total" in output
