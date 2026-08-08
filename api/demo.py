# api/demo.py
"""Whether the api is serving an offline demo (S4-6).

A deliberate copy of worker/llm/client.py's is_demo_offline(), not an import.
api/Dockerfile copies only api/, migrations/ and scripts/ into the image, so
`from worker...` here passes every local test and then kills the api container
on startup - a trap this repo has already walked into twice (the api-side
DamageType literal, the /health field before this file existed).

The api does not act on the flag; it only reports it. The decision that matters
- where an answer actually comes from - is made in the worker and rag services,
which read their own copy. This one exists so the cockpit can show a badge, and
so `curl /health` can answer "is this demo live or recorded" without a login.

Kept byte-identical to the worker's version on purpose: two spellings of "on"
would mean the badge and the pipeline could disagree about the same .env.
"""

import os

_ENV_TRUE_VALUES = frozenset({"true", "1", "yes"})


def is_demo_offline() -> bool:
    """Whether the offline demo mode is on. DEMO_OFFLINE, default off."""
    return os.environ.get("DEMO_OFFLINE", "false").strip().lower() in _ENV_TRUE_VALUES
