"""FastAPI REST API for the Cloud Right-Sizing Advisor.

Endpoints
  GET  /health            liveness + model/data status
  GET  /recommendations   filtered list of right-sizing recommendations
  GET  /summary           fleet-level spend / savings / risk summary
  POST /ingest            add or replace VM metrics, then recompute recommendations

The API is READ-ONLY with respect to your cloud: it never resizes anything.
Every recommendation carries requires_human_review = true.

Run:  uvicorn api.main:app --reload --port 8000
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime
from typing import Literal, Optional

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from model.recommender import (
    DATA_PATH, TIER_BY_NAME, ArtifactsMissingError, get_engine, load_metrics_csv,
    summarize,
)

app = FastAPI(
    title="Cloud Right-Sizing Advisor API",
    version="1.0.0",
    description="ML-driven VM right-sizing recommendations. Advisory only - no automated actions.",
)

_lock = threading.Lock()
_cache: dict = {"mtime": None, "recs": None}


def _records(df: pd.DataFrame) -> list[dict]:
    return json.loads(df.to_json(orient="records"))      # NaN -> null, numpy -> python


def _current_recs() -> pd.DataFrame:
    """Recompute recommendations only when the metrics file changed."""
    try:
        mtime = os.path.getmtime(DATA_PATH)
    except FileNotFoundError:
        raise HTTPException(404, "No metrics data found. Run `python scripts/generate_data.py` or POST /ingest.")
    with _lock:
        if _cache["recs"] is None or _cache["mtime"] != mtime:
            try:
                _cache["recs"] = get_engine().recommend(load_metrics_csv(DATA_PATH))
            except ArtifactsMissingError as e:
                raise HTTPException(503, str(e))
            except ValueError as e:
                raise HTTPException(422, str(e))
            _cache["mtime"] = mtime
        return _cache["recs"].copy()


# ── Schemas ────────────────────────────────────────────────────────────────────
class MetricRecord(BaseModel):
    """One metrics window for one VM. Extra columns are accepted; the maxima
    (maximum_usage_*) are optional and are NEVER used as model inputs."""
    model_config = ConfigDict(extra="allow")

    vm_id: str = Field(min_length=1)
    timestamp: datetime
    instance_type: str
    resource_request_cpus: float = Field(gt=0, le=1.0)
    resource_request_memory: float = Field(gt=0, le=1.0)
    average_usage_cpus: float = Field(ge=0)
    average_usage_memory: float = Field(ge=0)
    tail_cpu_usage_distribution_mean: float = Field(ge=0)
    priority: Optional[float] = None
    scheduling_class: Optional[float] = None
    collection_type: Optional[float] = None
    cpu_usage_distribution_mean: Optional[float] = None
    cpu_usage_distribution_std: Optional[float] = None
    duration: Optional[float] = None
    cycles_per_instruction: Optional[float] = None
    memory_accesses_per_instruction: Optional[float] = None
    failed: Optional[int] = None

    @field_validator("instance_type")
    @classmethod
    def _valid_tier(cls, v: str) -> str:
        v = v.lower()
        if v not in TIER_BY_NAME:
            raise ValueError(f"instance_type must be one of {list(TIER_BY_NAME)}")
        return v


class IngestRequest(BaseModel):
    records: list[MetricRecord] = Field(min_length=1, max_length=200_000)
    mode: Literal["append", "replace"] = "append"


# ── Endpoints ──────────────────────────────────────────────────────────────────
@app.get("/health")
def health() -> dict:
    models_ok, err = True, None
    try:
        get_engine()
    except ArtifactsMissingError as e:
        models_ok, err = False, str(e)
    return {
        "status": "ok" if models_ok and DATA_PATH.exists() else "degraded",
        "models_loaded": models_ok,
        "data_available": DATA_PATH.exists(),
        "detail": err,
        "automated_actions": "disabled - all recommendations require human review",
    }


@app.get("/recommendations")
def recommendations(
    action: Optional[Literal["downsize", "keep", "upsize"]] = None,
    risk_level: Optional[Literal["LOW", "MEDIUM", "HIGH"]] = None,
    min_confidence: float = Query(0, ge=0, le=100),
    max_failure_risk: float = Query(100, ge=0, le=100),
    vm_id: Optional[str] = None,
) -> dict:
    recs = _current_recs()
    if action:
        recs = recs[recs["action"] == action]
    if risk_level:
        recs = recs[recs["risk_level"] == risk_level]
    if vm_id:
        recs = recs[recs["vm_id"] == vm_id]
    recs = recs[(recs["confidence"] >= min_confidence) & (recs["failure_risk"] <= max_failure_risk)]
    return {"count": len(recs), "requires_human_review": True, "recommendations": _records(recs)}


@app.get("/summary")
def summary() -> dict:
    return summarize(_current_recs())


@app.post("/ingest")
def ingest(req: IngestRequest) -> dict:
    new = pd.DataFrame([r.model_dump(mode="json") for r in req.records])
    with _lock:
        if req.mode == "append" and DATA_PATH.exists():
            combined = pd.concat([load_metrics_csv(DATA_PATH), new], ignore_index=True)
        else:
            combined = new
        combined["timestamp"] = pd.to_datetime(combined["timestamp"], utc=True).dt.tz_convert(None)
        combined = combined.drop_duplicates(["vm_id", "timestamp"], keep="last")

        # Validate by actually running the engine BEFORE committing to disk.
        try:
            recs = get_engine().recommend(combined)
        except ArtifactsMissingError as e:
            raise HTTPException(503, str(e))
        except ValueError as e:
            raise HTTPException(422, str(e))

        DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=DATA_PATH.parent, suffix=".csv")
        os.close(fd)
        combined.to_csv(tmp, index=False)
        os.replace(tmp, DATA_PATH)
        _cache["recs"], _cache["mtime"] = recs, os.path.getmtime(DATA_PATH)

    return {
        "ingested_records": len(new),
        "total_rows": int(len(combined)),
        "vm_count": int(combined["vm_id"].nunique()),
        "mode": req.mode,
        "summary": summarize(recs),
    }
