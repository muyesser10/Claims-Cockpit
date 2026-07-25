# Claims Cockpit

An operations cockpit that ingests insurance claims from three channels
(email, call transcript, web form), masks personal data for compliance,
converts free text into structured data via LLM, and provides a
RAG-based Q&A interface for the operations team.

> **Status:** Sprint 1 / Day 1 — scaffolding in progress.

## Quick Start

```bash
git clone https://github.com/<YOUR-USERNAME>/claims-cockpit.git
cd claims-cockpit
cp .env.example .env      # fill in your API keys
docker compose up -d
```

Dashboard: http://localhost:5173 · API docs: http://localhost:8000/docs

## Prerequisites

| Tool | Version | Check |
| --- | --- | --- |
| Docker Desktop | 24+ | `docker --version` |
| Python | 3.11+ | `python --version` |
| Node.js | 20+ | `node --version` |
| Git | 2.40+ | `git --version` |

## Directory Structure

```
api/        FastAPI app (the only door to the outside world)
worker/     Pipeline steps: mask > classify > extract > validate > embed
web/        React + Vite cockpit UI
replay/     Simulator that feeds synthetic records into /ingest
eval/       Metric runner, rubrics, RAG question set
data/       Ground truth and generated text (not tracked in git)
prompts/    Versioned prompt files
schemas/    claim.json — SINGLE SOURCE OF TRUTH
docs/       Standup notes, ADRs, runbook, compliance notes
```

## Team

| Role | Short | Owner |
| --- | --- | --- |
| Data Engineer | DE | _name_ |
| LLM Engineer | LLM | _name_ |
| Data Scientist | DS | _name_ |
| Backend Engineer | BE | _name_ |
| Frontend Engineer | FE | _name_ |

## Working Agreements

- Trunk-based development: short-lived `feature/...` and `fix/...` branches
- Every PR needs at least 1 approval; you never merge your own PR
- `main` must be demoable at all times
- No merges to `main` after 4pm on Fridays
- Schema/contract changes carry a `[SCHEMA CHANGE]` tag in the PR title

Details: the `docs/` folder and the team's master guide (shared in Drive).
