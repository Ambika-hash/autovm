# Cloud Right-Sizing Advisor

Reads 30 days of VM metrics, predicts the **realistic peak CPU and memory** each VM needs with a
leakage-free Random Forest, and recommends the smallest instance tier that still leaves a 30% safety
buffer - with the monthly saving, a confidence score, a failure-risk score and a risk level.

> **Advisory only.** The system never resizes anything. Every recommendation carries
> `requires_human_review = true`, and `automated_actions_taken` is always `0`.

## Quick start

```bash
pip install -r requirements.txt            # Python 3.10
python scripts/generate_data.py            # 15 over-provisioned demo VMs, 30 days
python -m model.train                      # trains + saves models to artifacts/
streamlit run dashboard/app.py             # dashboard  -> http://localhost:8501
# separately:
uvicorn api.main:app --reload --port 8000  # API docs   -> http://localhost:8000/docs
```

Optional: `python -m model.recommender` prints the recommendations and writes `data/recommendations.csv`.

### Docker

```bash
docker build -t rightsizing .
docker run -p 8000:8000 -p 8501:8501 rightsizing
```

The image generates demo data and trains the models at build time; `start.sh` re-does either if you mount
empty volumes over `data/` or `artifacts/`.

## How it works

```
vm_metrics.csv --> engineer features --> Random Forests --> p99 predicted peak
                                                                 |
              confidence / failure risk / risk level  <--  x1.30 buffer -> smallest fitting tier -> savings
```

1. **Features** (`model/train.py`) - the research paper's engineered features, used exactly:
   - `cpu_efficiency = average_usage_cpus / resource_request_cpus`
   - `mem_efficiency = average_usage_memory / resource_request_memory`
   - `tail_cpu_ratio = tail_cpu_usage_distribution_mean / average_usage_cpus`
   (plus the paper's raw features and `priority_tier`; values are clipped as in the paper.)
2. **Leakage-free design.** `maximum_usage_cpus` and `maximum_usage_memory` are prediction **targets only**.
   `cpu_burst_ratio` and `cpu_range` from the paper are removed too, because they are computed from the
   maximum. `assert_no_leakage()` runs at import time, on every feature-matrix build, when training and when
   models are loaded; any forbidden column raises `LeakageError` with a clear message. Inference does not need
   the maxima at all, so `/ingest` accepts data without them.
3. **Validation** is chronological (train on the first 80% of the timeline, test on the last 20%).
4. **Realistic peak** = 99th percentile of the per-window predicted peaks (so rare bursts are not ignored),
   never lower than the observed p99 of average usage.
5. **Safety buffer.** Required capacity = predicted peak x **1.30**; the recommendation is the smallest tier
   whose CPU *and* memory both cover that, so it is always strictly above the predicted peak - never exactly at it.
6. **Confidence (0-100)** = 50% agreement between the 200 trees + 30% holdout R2 + 20% data coverage.
7. **Failure risk (%)** = the failure classifier's mean probability for the VM's last 7 days *as if it ran on
   the recommended tier* (the efficiency features are recomputed against the new capacity).
8. **Risk level** - `HIGH` if failure risk >= 10% or confidence < 50; `MEDIUM` if failure risk >= 5% or
   confidence < 70; otherwise `LOW`. (Thresholds are constants at the top of `model/recommender.py`.)

### Instance tiers (normalised against 32 cores / 128 GB)

| Tier | CPU fraction | Memory fraction | $/month |
|---|---|---|---|
| micro | 1/32 | 2/128 | 15 |
| small | 2/32 | 4/128 | 30 |
| medium | 4/32 | 8/128 | 60 |
| large | 8/32 | 16/128 | 120 |
| xlarge | 16/32 | 32/128 | 240 |
| 2xlarge | 32/32 | 64/128 | 480 |

## API

| Endpoint | Purpose |
|---|---|
| `GET /health` | status of models and data |
| `GET /recommendations` | filters: `action` (downsize/keep/upsize), `risk_level`, `min_confidence`, `max_failure_risk`, `vm_id` |
| `GET /summary` | spend, potential savings, counts by action and risk level |
| `POST /ingest` | `{"records": [...], "mode": "append" \| "replace"}`; validated by running the model before anything is saved |

Required fields per record: `vm_id`, `timestamp`, `instance_type`, `resource_request_cpus`,
`resource_request_memory`, `average_usage_cpus`, `average_usage_memory`, `tail_cpu_usage_distribution_mean`.
CPU and memory values are fractions of the largest machine (32 cores / 128 GB). Optional fields
(`priority`, `scheduling_class`, `collection_type`, `cpu_usage_distribution_mean/std`, `duration`,
`cycles_per_instruction`, `memory_accesses_per_instruction`) fall back to training-set medians.
`maximum_usage_*` may be included for charting but is never used as a model input.

```bash
curl "localhost:8000/recommendations?action=downsize&risk_level=LOW"
curl localhost:8000/summary
```

## Demo data

15 VMs, 30 days, 4 six-hour windows per day. Idle, web and API VMs are heavily over-provisioned and get
downsized. Batch and CI VMs look idle on average (6-9%) but burst to 40-60% of their instance, so the
model **keeps** them - this is exactly what average-based tools get wrong. The DB, ML, cache and monitor VMs are
kept; cache is memory-bound.

## Project layout

```
scripts/generate_data.py   synthetic data         model/train.py        features + training + leakage guard
model/recommender.py       tiers, savings, risk   api/main.py           FastAPI service
dashboard/app.py           Streamlit + Plotly     Dockerfile, start.sh  container runtime
```

## Production notes

- Replace the synthetic CSV with real exports in the same schema (via `/ingest` or `data/vm_metrics.csv`),
  then retrain: `python -m model.train` (the training data needs the `maximum_usage_*` targets).
- The failure model is trained on the `failed` column; if you have no such label, it falls back to a
  prior-only classifier and failure risk becomes a constant - treat it accordingly.
- Re-train regularly; saved models are pickles and must be loaded with the pinned scikit-learn version.
