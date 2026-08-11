# Claims Cockpit

A decision-support system that automatically classifies, prioritizes, and triages insurance claim reports. It takes free-text claims from email, call transcripts, and web forms; masks personal data, extracts structured fields, ranks by urgency, and routes them into a queue an operator can approve from a single screen. It also answers natural-language questions about the data ("how many hail claims are there in İzmir?").

Built with a zero budget, a team of five, over four sprints.

## What it does

An insurer receives hundreds of claims a day across different channels. They are not equal: some are urgent (an injury accident), some are just a question, some are entirely off-topic. Claims Cockpit processes this stream automatically:

- **Masking** — masks personal data (name, phone, national ID, plate, policy number, IBAN) before extraction; raw personal data never leaves for a third-party service.
- **Classification** — determines the message type (real claim / info request / irrelevant) and urgency (critical / high / normal). Injury means critical.
- **Extraction** — turns policy number, plate, incident date, location, damage type, estimated amount into structured fields; never invents information that isn't in the text.
- **Validation** — checks the extracted data for consistency with 11 rules.
- **Triage queue** — routes suspicious or critical records to operator review; the operator approves/rejects quickly with keyboard shortcuts.
- **Question answering (RAG)** — the data can be queried in natural language; the system answers both aggregate queries (Text-to-SQL) and textual searches (retrieval), always grounding its answer in a source.

## Architecture

The system is built around a message queue:

```
Claim (email / transcript / form)
        │
        ▼
    /ingest  ──►  Redis queue  ──►  Worker pipeline
                                        │
                                        ├─ masking (regex + name dictionary)
                                        ├─ masking sanity (leaked-PII check)
                                        ├─ classification (type + urgency)
                                        ├─ routing
                                        ├─ extraction
                                        ├─ validation (11 rules)
                                        ├─ embedding (vector)
                                        └─ auto-approval gate
                                        │
                                        ▼
                            /claims + /queue (JWT protected)
                                        │
                    ┌───────────────────┼───────────────────┐
                    ▼                   ▼                   ▼
                Dashboard           Review Queue         Ask (/soru)
            (counters / donut /     (keyboard UX,        (RAG: SQL or
             city bar / trend)       fast approve)        retrieval)
```

Services: PostgreSQL (with pgvector), Redis, API (FastAPI), Worker, RAG service, Web (React/Vite), Prometheus, Grafana.

## Tech stack

- **Backend:** Python 3.11, FastAPI, SQLAlchemy (sync, psycopg3), Alembic
- **Queue:** Redis
- **Database:** PostgreSQL + pgvector (384-dim embeddings)
- **LLM:** OpenAI (two tiers: gpt-4o-mini / gpt-4o), structured output via instructor + Pydantic
- **Embedding:** `intfloat/multilingual-e5-small` (local, 384-dim)
- **Frontend:** React + Vite + TypeScript, Tailwind
- **Observability:** Prometheus + Grafana
- **Auth:** JWT (HS256), role-based (operator / admin)
- **Synthetic data:** Faker (tr_TR)

## Setup

Requires Docker + Docker Compose.

```bash
# 1. Clone the repository
git clone https://github.com/muyesser10/Claims-Cockpit.git
cd claims-cockpit

# 2. Prepare environment variables
cp .env.example .env
# Add OPENAI_API_KEY to .env (not needed for the offline demo, see below)

# 3. Bring up the services
docker compose up -d --build

# 4. Apply the database schema
alembic upgrade head

# 5. Create the read-only role (for RAG's Text-to-SQL path, once)
# Command in docs/runbook.md

# 6. Create an operator user
python scripts/create_user.py

# 7. Health check
curl http://localhost:8000/health
```

Once up, the dashboard is at `http://localhost:5173` and the API docs at `http://localhost:8000/docs`. Log in with the user you created.

## Usage

### Data generation and replay

The system runs on synthetic data. Ground truth and texts are produced by generators:

```bash
# Generate 1000 ground-truth records
python data/gt_generator.py --count 1000

# Generate texts for the three channels (email / transcript / form)
python data/text_generator.py --count 1000
```

Replay feeds the generated texts into the system:

```bash
# Post all records to /ingest in order (--dry-run to preview)
python replay/replay.py --dry-run

# Run the demo scenario with choreography (normal flow, then an İzmir hail surge)
python replay/replay.py --scenario replay/scenarios/demo.yaml --dry-run
```

### Asking questions

Questions can be asked in natural language from the Ask screen in the operator dashboard, or via the `/soru` endpoint. The system answers via one of two paths: numeric/aggregate questions through Text-to-SQL ("how many critical claims are there"), textual questions through vector search ("what do the hail claims say"). The answer is always grounded in a source; an ungrounded answer is not shown.

## Offline demo

The system is designed to run a full demo without internet or an OpenAI key. When the `DEMO_OFFLINE` flag is on, only the lowest-level LLM calls are swapped for recorded answers (`demo/fixtures/`); everything else — masking, embedding, SQL, validation — runs through the real code path.

```bash
# Seed the demo database reproducibly (60 records)
python demo/seed_demo_db.py
```

## Data privacy

Personal-data protection is central to the system:

- Raw personal data (name, phone, national ID, plate, policy number) is masked before being sent to the LLM.
- Masking is two-layered: regex (structured PII) + a name dictionary (~1550 names). Names that collide with everyday words (like Deniz, Yağmur) are masked only when there is a contextual signal.
- After masking, an LLM sanity layer checks for leaked PII; if a leak is found, extraction is skipped entirely.
- The masking check result is written to the database as **type and location only**, never raw text.

## Project structure

```
api/           FastAPI application (endpoints, auth, models)
worker/        Pipeline: masking, classification, extraction, validation, RAG
data/          Synthetic data generators (ground truth + three-channel text) + dictionaries
replay/        Replay that feeds records into /ingest + demo scenarios
eval/          Evaluation backbone (metrics, scoring)
web/           React/Vite frontend
demo/          Offline demo (fixtures, seed)
monitoring/    Prometheus + Grafana configuration
schemas/       claim.json — the data contract
```

## Metric journey

Quality indicators measured over the project:

- **Extraction accuracy:** %99.4 on the first measurement (100 records); being re-measured because the corpus was regenerated.
- **Injury-detection precision:** %18.5 → %98.8 (after a matching fix).
- **Masking:** ~1550-name dictionary + context rule + LLM sanity layer.
- **Name recall on the evaluation set** is no longer circular: part of the data is generated with out-of-dictionary (holdout) names, so masking's real performance on names it hasn't seen can be measured.

## Team

A team of five, covering Backend, Frontend, Data Engineering, LLM/RAG, and Data Science roles. Each role worked from its own guide, around a shared `CLAUDE.md` (fixed rules) and `STATUS.md` (live status).

## Phase 2 roadmap

- Opening the auto-approval gate (after precision measurement)
- RAG evaluation set and scoring
- Fallback LLM layer (providers other than OpenAI)
- Real-time error center
- An official name/surname dictionary source

---

For fixed rules see `CLAUDE.md`, for current status see `STATUS.md`.