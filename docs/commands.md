# Useful Commands Cheat Sheet

```bash
# Bring the system up
docker compose up -d

# Service status
docker compose ps

# Run migrations
docker compose exec api alembic upgrade head

# Scale up workers
docker compose up -d --scale worker=3

# Start replay
python replay/replay.py --count 50 --speed 5x --mix email:5,transcript:3,form:2

# Run eval
python eval/run_eval.py --set test --run-name week2-v3

# Generate ground truth
python data/gt_generator.py --seed 42 --count 100

# Demo fallback (LLM providers down)
DEMO_OFFLINE=true docker compose up

# Tail logs
docker compose logs -f worker

# Connect to Postgres
docker compose exec db psql -U claims -d claims_cockpit

# Full reset (WARNING: deletes data)
docker compose down -v
```
