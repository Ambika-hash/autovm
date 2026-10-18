"""Recommendation engine: predicted peak -> instance tier -> cost savings.

For every VM it
  1. predicts realistic peak CPU and memory (leakage-free Random Forests),
  2. adds a 30% safety buffer and picks the smallest instance tier that covers it
     (so the recommended capacity is ALWAYS strictly above the predicted peak),
  3. estimates monthly savings,
  4. attaches a confidence score, a failure-risk score and a risk level.

It NEVER takes automated action: every recommendation is advisory and
`requires_human_review` is always True.

Run:  python -m model.recommender      (prints recommendations, writes data/recommendations.csv)
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from model.train import (
    ARTIFACT_DIR, DATA_PATH, FEATURE_COLS, REQUIRED_INPUT, assert_no_leakage,
    build_feature_matrix, engineer_features,
)

ROOT = Path(__file__).resolve().parents[1]
RECS_PATH = ROOT / "data" / "recommendations.csv"

MAX_CORES, MAX_MEM_GB = 32, 128
SAFETY_BUFFER = 0.30          # recommended capacity >= predicted peak * 1.30
PEAK_PERCENTILE = 99          # "realistic peak" = p99 of per-window predicted peaks (catches rare bursts)
WINDOWS_FOR_FULL_COVERAGE = 120   # 30 days x 4 windows/day
FAILURE_LOOKBACK_DAYS = 7

# Risk-level thresholds
HIGH_FAILURE_RISK, MEDIUM_FAILURE_RISK = 10.0, 5.0   # percent
LOW_CONFIDENCE, MEDIUM_CONFIDENCE = 50.0, 70.0       # score out of 100


@dataclass(frozen=True)
class Tier:
    name: str
    cores: int
    mem_gb: int
    monthly_cost: float

    @property
    def cpu_fraction(self) -> float:
        return self.cores / MAX_CORES

    @property
    def mem_fraction(self) -> float:
        return self.mem_gb / MAX_MEM_GB


TIERS: list[Tier] = [
    Tier("micro", 1, 2, 15.0),
    Tier("small", 2, 4, 30.0),
    Tier("medium", 4, 8, 60.0),
    Tier("large", 8, 16, 120.0),
    Tier("xlarge", 16, 32, 240.0),
    Tier("2xlarge", 32, 64, 480.0),
]
TIER_BY_NAME = {t.name: t for t in TIERS}
TIER_INDEX = {t.name: i for i, t in enumerate(TIERS)}


def smallest_fitting_tier(cpu_needed: float, mem_needed: float) -> tuple[Tier, bool]:
    """Smallest tier whose CPU *and* memory both cover the need. Returns (tier, fits)."""
    for t in TIERS:
        if t.cpu_fraction >= cpu_needed and t.mem_fraction >= mem_needed:
            return t, True
    return TIERS[-1], False


def risk_level(failure_risk: float, confidence: float) -> str:
    if failure_risk >= HIGH_FAILURE_RISK or confidence < LOW_CONFIDENCE:
        return "HIGH"
    if failure_risk >= MEDIUM_FAILURE_RISK or confidence < MEDIUM_CONFIDENCE:
        return "MEDIUM"
    return "LOW"


class ArtifactsMissingError(RuntimeError):
    pass


# ── Input validation ───────────────────────────────────────────────────────────
def prepare_metrics(df: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in REQUIRED_INPUT if c not in df.columns]
    if missing:
        raise ValueError(f"Metrics data is missing required columns: {missing}")
    out = df.copy()
    out["vm_id"] = out["vm_id"].astype(str)
    out["instance_type"] = out["instance_type"].astype(str).str.lower()
    unknown = sorted(set(out["instance_type"]) - set(TIER_BY_NAME))
    if unknown:
        raise ValueError(f"Unknown instance_type value(s) {unknown}; valid: {list(TIER_BY_NAME)}")
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True).dt.tz_convert(None)
    num = [c for c in REQUIRED_INPUT if c not in ("vm_id", "timestamp", "instance_type")]
    out[num] = out[num].apply(pd.to_numeric, errors="coerce")
    out = out.dropna(subset=num).drop_duplicates(["vm_id", "timestamp"], keep="last")
    if out.empty:
        raise ValueError("No valid metric rows after cleaning.")
    return out.sort_values(["vm_id", "timestamp"]).reset_index(drop=True)


def load_metrics_csv(path: Path = DATA_PATH) -> pd.DataFrame:
    if not Path(path).exists():
        raise FileNotFoundError(f"{path} not found. Run: python scripts/generate_data.py")
    return pd.read_csv(path)


# ── Engine ─────────────────────────────────────────────────────────────────────
class RightSizingEngine:
    def __init__(self, artifact_dir: Path = ARTIFACT_DIR):
        files = {
            "cpu": "cpu_peak_model.pkl", "mem": "memory_peak_model.pkl",
            "fail": "failure_model.pkl", "scaler": "scaler.pkl", "meta": "metadata.json",
        }
        missing = [f for f in files.values() if not (Path(artifact_dir) / f).exists()]
        if missing:
            raise ArtifactsMissingError(
                f"Model artifacts missing in {artifact_dir}: {missing}. Run: python -m model.train")
        self.meta = json.loads((Path(artifact_dir) / files["meta"]).read_text())
        self.features = self.meta["features"]
        assert_no_leakage(self.features)                 # guard against tampered artifacts
        if self.features != FEATURE_COLS:
            raise RuntimeError("Saved model features differ from FEATURE_COLS - retrain: python -m model.train")
        self.defaults = self.meta["defaults"]
        self.cpu_model = joblib.load(Path(artifact_dir) / files["cpu"])
        self.mem_model = joblib.load(Path(artifact_dir) / files["mem"])
        self.fail_model = joblib.load(Path(artifact_dir) / files["fail"])
        self.scaler = joblib.load(Path(artifact_dir) / files["scaler"])
        m = self.meta["metrics"]
        self.model_r2 = max(min(m["cpu_peak"]["R2"], m["memory_peak"]["R2"]), 0.0)

    # -- helpers
    def _scaled(self, feat_df: pd.DataFrame) -> pd.DataFrame:
        X = build_feature_matrix(feat_df, self.defaults)   # leakage assertion
        Xs = pd.DataFrame(self.scaler.transform(X[self.features]), columns=self.features)
        assert_no_leakage(Xs.columns)
        return Xs

    @staticmethod
    def _tree_matrix(model, Xs: pd.DataFrame) -> np.ndarray:
        arr = Xs.to_numpy(dtype=np.float32)    # individual trees are fitted without feature names
        return np.stack([t.predict(arr) for t in model.estimators_])   # (n_trees, n_rows)

    def _failure_risk(self, vm_feat: pd.DataFrame, tier: Tier) -> float:
        """Mean failure probability (%) if this VM's recent workload ran on `tier`."""
        recent = vm_feat[vm_feat["timestamp"] >=
                         vm_feat["timestamp"].max() - pd.Timedelta(days=FAILURE_LOOKBACK_DAYS)].copy()
        recent["resource_request_cpus"] = tier.cpu_fraction
        recent["resource_request_memory"] = tier.mem_fraction
        recent = engineer_features(recent)               # recompute efficiencies on the new tier
        proba = self.fail_model.predict_proba(self._scaled(recent))
        classes = list(self.fail_model.classes_)
        p = proba[:, classes.index(1)] if 1 in classes else np.zeros(len(recent))
        return float(np.mean(p) * 100)

    # -- main entry point
    def recommend(self, metrics: pd.DataFrame) -> pd.DataFrame:
        df = prepare_metrics(metrics)
        feat = engineer_features(df)
        Xs = self._scaled(feat)
        cpu_trees = self._tree_matrix(self.cpu_model, Xs)
        mem_trees = self._tree_matrix(self.mem_model, Xs)

        has_obs = "maximum_usage_cpus" in df.columns and "maximum_usage_memory" in df.columns
        rows = []
        for vm_id, idx in feat.groupby("vm_id").indices.items():
            g = feat.iloc[idx]
            cur = TIER_BY_NAME[g["instance_type"].iloc[-1]]

            def peak(trees, avg_series):
                per_tree = np.percentile(trees[:, idx], PEAK_PERCENTILE, axis=1)
                mean = float(per_tree.mean())
                cv = float(per_tree.std() / mean) if mean > 0 else 1.0
                floor = float(np.percentile(avg_series, PEAK_PERCENTILE))   # peak can't be below avg
                return max(mean, floor), cv

            peak_cpu, cv_cpu = peak(cpu_trees, g["average_usage_cpus"])
            peak_mem, cv_mem = peak(mem_trees, g["average_usage_memory"])

            need_cpu, need_mem = peak_cpu * (1 + SAFETY_BUFFER), peak_mem * (1 + SAFETY_BUFFER)
            rec, fits = smallest_fitting_tier(need_cpu, need_mem)
            if fits and not (rec.cpu_fraction > peak_cpu and rec.mem_fraction > peak_mem):
                raise RuntimeError(f"Safety-buffer invariant violated for {vm_id}")   # defensive

            cpu_only, _ = smallest_fitting_tier(need_cpu, 0)
            mem_only, _ = smallest_fitting_tier(0, need_mem)
            binding = "memory" if TIER_INDEX[mem_only.name] > TIER_INDEX[cpu_only.name] else "CPU"

            # Confidence: tree agreement (50%) + holdout R2 (30%) + data coverage (20%)
            agreement = 1 - min(max(cv_cpu, cv_mem) * 4, 1)
            coverage = min(len(g) / WINDOWS_FOR_FULL_COVERAGE, 1)
            confidence = 100 * (0.5 * agreement + 0.3 * self.model_r2 + 0.2 * coverage)

            fail_risk = self._failure_risk(g, rec)
            level = risk_level(fail_risk, confidence)

            if TIER_INDEX[rec.name] < TIER_INDEX[cur.name]:
                action = "downsize"
            elif TIER_INDEX[rec.name] > TIER_INDEX[cur.name]:
                action = "upsize"
            else:
                action = "keep"

            avg_cpu = float(g["average_usage_cpus"].mean())
            burst_ratio = peak_cpu / avg_cpu if avg_cpu > 0 else float("nan")
            cpu_pct_cur, mem_pct_cur = 100 * peak_cpu / cur.cpu_fraction, 100 * peak_mem / cur.mem_fraction

            if action == "downsize":
                reason = (f"Predicted peak is {cpu_pct_cur:.0f}% CPU / {mem_pct_cur:.0f}% memory of the "
                          f"current {cur.name}. {rec.name} is the smallest tier with >=30% headroom "
                          f"({binding}-bound).")
            elif action == "upsize":
                reason = (f"Predicted peak ({cpu_pct_cur:.0f}% CPU / {mem_pct_cur:.0f}% memory of current "
                          f"{cur.name}) plus 30% buffer exceeds current capacity"
                          + ("" if fits else "; even the largest tier is below the buffered need") + ".")
            else:
                reason = (f"Current {cur.name} is already the right size: predicted peak "
                          f"{cpu_pct_cur:.0f}% CPU / {mem_pct_cur:.0f}% memory, {binding}-bound.")
            if burst_ratio >= 4:
                reason += (f" Burst-protected: peak is {burst_ratio:.1f}x average usage, so average "
                           "utilisation alone would understate the need.")

            row = {
                "vm_id": vm_id,
                "current_tier": cur.name,
                "current_monthly_cost": cur.monthly_cost,
                "recommended_tier": rec.name,
                "recommended_monthly_cost": rec.monthly_cost,
                "action": action,
                "monthly_savings": cur.monthly_cost - rec.monthly_cost,
                "annual_savings": 12 * (cur.monthly_cost - rec.monthly_cost),
                "avg_cpu_util_pct": 100 * avg_cpu / cur.cpu_fraction,
                "avg_mem_util_pct": 100 * float(g["average_usage_memory"].mean()) / cur.mem_fraction,
                "predicted_peak_cpu": peak_cpu,
                "predicted_peak_memory": peak_mem,
                "predicted_peak_cpu_pct_of_current": cpu_pct_cur,
                "predicted_peak_mem_pct_of_current": mem_pct_cur,
                "required_cpu_with_buffer": need_cpu,
                "required_mem_with_buffer": need_mem,
                "burst_ratio": burst_ratio,
                "binding_resource": binding,
                "confidence": round(confidence, 1),
                "failure_risk": round(fail_risk, 1),
                "risk_level": level,
                "observed_peak_cpu_pct_of_current": (
                    100 * float(g["maximum_usage_cpus"].max()) / cur.cpu_fraction if has_obs else np.nan),
                "observed_peak_mem_pct_of_current": (
                    100 * float(g["maximum_usage_memory"].max()) / cur.mem_fraction if has_obs else np.nan),
                "windows_analyzed": int(len(g)),
                "fits_largest_tier": bool(fits),
                "reason": reason,
                "requires_human_review": True,
            }
            rows.append(row)

        recs = pd.DataFrame(rows).sort_values("monthly_savings", ascending=False).reset_index(drop=True)
        return recs


def summarize(recs: pd.DataFrame) -> dict:
    down = recs[recs["action"] == "downsize"]
    spend = float(recs["current_monthly_cost"].sum())
    savings = float(down["monthly_savings"].sum())
    return {
        "vm_count": int(len(recs)),
        "current_monthly_spend": spend,
        "potential_monthly_savings": savings,
        "potential_annual_savings": 12 * savings,
        "savings_pct_of_spend": round(100 * savings / spend, 1) if spend else 0.0,
        "low_risk_monthly_savings": float(down.loc[down["risk_level"] == "LOW", "monthly_savings"].sum()),
        "by_action": {k: int(v) for k, v in recs["action"].value_counts().items()},
        "by_risk_level": {k: int(v) for k, v in recs["risk_level"].value_counts().items()},
        "avg_confidence": round(float(recs["confidence"].mean()), 1),
        "avg_failure_risk": round(float(recs["failure_risk"].mean()), 1),
        "safety_buffer": SAFETY_BUFFER,
        "automated_actions_taken": 0,
        "requires_human_review": True,
    }


@lru_cache(maxsize=1)
def get_engine() -> RightSizingEngine:
    return RightSizingEngine()


def reset_engine_cache() -> None:
    get_engine.cache_clear()


def compute_recommendations(path: Path = DATA_PATH) -> pd.DataFrame:
    return get_engine().recommend(load_metrics_csv(path))


if __name__ == "__main__":
    r = compute_recommendations()
    RECS_PATH.parent.mkdir(parents=True, exist_ok=True)
    r.to_csv(RECS_PATH, index=False)
    cols = ["vm_id", "current_tier", "recommended_tier", "action", "monthly_savings",
            "confidence", "failure_risk", "risk_level"]
    print(r[cols].to_string(index=False))
    print(json.dumps(summarize(r), indent=2))
    print(f"\nWrote {RECS_PATH}")
