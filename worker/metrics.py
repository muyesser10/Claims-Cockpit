# worker/metrics.py
"""Pipeline metrics for Prometheus (S3-9).

Exposed over HTTP by prometheus_client.start_http_server(9100), started in
worker/main.py — this is a plain metric-definition module, no server logic
here, same separation as api/metrics.py (definitions) vs api/main.py
(wiring).
"""

from prometheus_client import Counter, Gauge, Histogram

# --- LLM usage ---------------------------------------------------------------
#
# Deliberately no worker_ prefix, unlike everything else in this file. These two
# are incremented inside worker/llm/client.py, which the rag service loads as
# well — prometheus_client keeps one global registry per process, so the same
# counters are also exported on rag:8100/metrics (monitoring/prometheus.yml
# scrapes all three services). A worker_ prefix would misname RAG's four calls.
#
# The first metrics here to carry labels. Cardinality stays small and bounded:
# two models × two tiers × two kinds = 8 series.

llm_tokens_total = Counter(
    "llm_tokens_total",
    "Tokens billed by the provider, as reported in completion.usage",
    ["model", "tier", "kind"],  # kind: prompt | completion
)

llm_calls_total = Counter(
    "llm_calls_total",
    "structured() calls, by how they ended",
    ["model", "tier", "outcome"],  # outcome: ok | error
)

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
