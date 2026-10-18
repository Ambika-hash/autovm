#!/usr/bin/env bash
# Starts the FastAPI service (8000) and the Streamlit dashboard (8501) together.
set -euo pipefail
cd "$(dirname "$0")"

# First-run bootstrap (e.g. when /app/data or /app/artifacts is a fresh volume).
if [ ! -f data/vm_metrics.csv ]; then
  echo "[start] No metrics data found - generating demo data..."
  python scripts/generate_data.py
fi
if [ ! -f artifacts/metadata.json ]; then
  echo "[start] No trained models found - training..."
  python -m model.train
fi

API_PORT="${API_PORT:-8000}"
DASH_PORT="${DASHBOARD_PORT:-8501}"

uvicorn api.main:app --host 0.0.0.0 --port "$API_PORT" &
API_PID=$!
streamlit run dashboard/app.py --server.port "$DASH_PORT" --server.address 0.0.0.0 \
  --server.headless true &
DASH_PID=$!

cleanup() { kill "$API_PID" "$DASH_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

echo "[start] API:       http://localhost:${API_PORT}/docs"
echo "[start] Dashboard: http://localhost:${DASH_PORT}"

# Exit (and let Docker restart us) as soon as either process dies.
wait -n "$API_PID" "$DASH_PID"
