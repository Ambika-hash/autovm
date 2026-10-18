"""Feature engineering + Random Forest training (LEAKAGE-FREE).

Targets
  * maximum_usage_cpus     -> realistic peak CPU    (regression)
  * maximum_usage_memory   -> realistic peak memory (regression)
  * failed                 -> job-failure probability (classification)

`maximum_usage_cpus` / `maximum_usage_memory` are TARGETS ONLY. They - and anything
derived from them (cpu_burst_ratio, cpu_range from the research paper) - can never
enter the feature matrix: `assert_no_leakage` crashes with a LeakageError if they do.

Run:  python -m model.train
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score, roc_auc_score
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "vm_metrics.csv"
ARTIFACT_DIR = ROOT / "artifacts"

# ── Columns ────────────────────────────────────────────────────────────────────
TARGET_CPU = "maximum_usage_cpus"
TARGET_MEM = "maximum_usage_memory"
TARGET_FAIL = "failed"

# Columns that must NEVER be model inputs (targets + features derived from targets).
FORBIDDEN_COLUMNS = frozenset({
    "maximum_usage_cpus", "maximum_usage_memory", "cpu_burst_ratio", "cpu_range",
})

# Minimum columns a metrics file must contain. Used for inference too - note that
# the maxima are NOT required at inference time.
REQUIRED_INPUT = [
    "vm_id", "timestamp", "instance_type",
    "resource_request_cpus", "resource_request_memory",
    "average_usage_cpus", "average_usage_memory",
    "tail_cpu_usage_distribution_mean",
]

RAW_FEATURES = [
    "resource_request_cpus", "resource_request_memory",
    "priority", "scheduling_class", "collection_type",
    "average_usage_cpus", "average_usage_memory",
    "cpu_usage_distribution_mean", "cpu_usage_distribution_std",
    "tail_cpu_usage_distribution_mean",
    "duration", "cycles_per_instruction", "memory_accesses_per_instruction",
]
ENGINEERED_FEATURES = ["cpu_efficiency", "mem_efficiency", "tail_cpu_ratio", "priority_tier"]
FEATURE_COLS = RAW_FEATURES + ENGINEERED_FEATURES

N_TREES = 200
MAX_DEPTH = 10
TRAIN_FRACTION = 0.8   # chronological split: first 80% of time -> train, rest -> test


class LeakageError(AssertionError):
    """Raised when a target (or a target-derived column) enters the feature matrix."""


def assert_no_leakage(columns) -> None:
    """Crash loudly if any forbidden column is present in the feature matrix."""
    cols = [str(c) for c in columns]
    bad = sorted({c for c in cols if c in FORBIDDEN_COLUMNS or "maximum_usage" in c})
    if bad:
        raise LeakageError(
            f"DATA LEAKAGE DETECTED: forbidden column(s) {bad} found in the feature matrix. "
            "maximum_usage_cpus / maximum_usage_memory are prediction TARGETS and may never be "
            "used as inputs (nor anything derived from them, e.g. cpu_burst_ratio, cpu_range). "
            "Remove them from FEATURE_COLS."
        )


# Fail at import time if someone edits FEATURE_COLS carelessly.
assert_no_leakage(FEATURE_COLS)


# ── Feature engineering ────────────────────────────────────────────────────────
def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add the paper's engineered features (formulas used exactly as published)."""
    out = df.copy()
    out["cpu_efficiency"] = (out["average_usage_cpus"]
                             / out["resource_request_cpus"].replace(0, np.nan)).clip(0, 2)
    out["mem_efficiency"] = (out["average_usage_memory"]
                             / out["resource_request_memory"].replace(0, np.nan)).clip(0, 2)
    out["tail_cpu_ratio"] = (out["tail_cpu_usage_distribution_mean"]
                             / out["average_usage_cpus"].replace(0, np.nan)).clip(0, 10)
    if "priority" in out.columns:
        prio = pd.to_numeric(out["priority"], errors="coerce")
        out["priority_tier"] = pd.cut(prio, bins=[-1, 99, 115, 500], labels=[0, 1, 2]).astype(float)
    else:
        out["priority_tier"] = np.nan
    return out


def build_feature_matrix(df: pd.DataFrame, defaults: dict | None = None) -> pd.DataFrame:
    """Select FEATURE_COLS, fill gaps, and enforce the leakage-free guarantee."""
    defaults = defaults or {}
    X = df.reindex(columns=FEATURE_COLS).apply(pd.to_numeric, errors="coerce")
    X = X.replace([np.inf, -np.inf], np.nan)
    for c in FEATURE_COLS:
        fill = defaults.get(c, X[c].median())
        X[c] = X[c].fillna(0.0 if pd.isna(fill) else fill)
    assert_no_leakage(X.columns)
    return X


def load_metrics(path: Path = DATA_PATH) -> pd.DataFrame:
    if not Path(path).exists():
        raise FileNotFoundError(f"{path} not found. Run: python scripts/generate_data.py")
    df = pd.read_csv(path)
    missing = [c for c in REQUIRED_INPUT + [TARGET_CPU, TARGET_MEM] if c not in df.columns]
    if missing:
        raise ValueError(f"Training data is missing required columns: {missing}")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert(None)
    return df.sort_values(["timestamp", "vm_id"]).reset_index(drop=True)


# ── Training ───────────────────────────────────────────────────────────────────
def _regressor() -> RandomForestRegressor:
    return RandomForestRegressor(n_estimators=N_TREES, max_depth=MAX_DEPTH,
                                 min_samples_leaf=2, random_state=42, n_jobs=-1)


def _eval_reg(y_true, y_pred) -> dict:
    return {
        "MAE": float(mean_absolute_error(y_true, y_pred)),
        "RMSE": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        "R2": float(r2_score(y_true, y_pred)),
    }


def train(data_path: Path = DATA_PATH, artifact_dir: Path = ARTIFACT_DIR) -> dict:
    t0 = time.time()
    print("=" * 62 + "\nCLOUD RIGHT-SIZING ADVISOR - MODEL TRAINING (leakage-free)\n" + "=" * 62)

    df = engineer_features(load_metrics(data_path))
    print(f"Loaded {len(df):,} rows, {df['vm_id'].nunique()} VMs")

    X = build_feature_matrix(df)          # <- runtime leakage assertion happens here
    assert_no_leakage(X.columns)
    print(f"Feature matrix: {X.shape[1]} features, leakage check PASSED")
    print("  forbidden (targets only):", ", ".join(sorted(FORBIDDEN_COLUMNS)))

    # Chronological split: never train on the future.
    cutoff = df["timestamp"].quantile(TRAIN_FRACTION)
    tr = (df["timestamp"] <= cutoff).to_numpy()
    te = (df["timestamp"] > cutoff).to_numpy()
    print(f"Chronological split at {cutoff:%Y-%m-%d %H:%M}: train={tr.sum():,}  test={te.sum():,}")

    defaults = {c: float(X.loc[tr, c].median()) for c in FEATURE_COLS}
    scaler = StandardScaler().fit(X[tr])
    Xs = pd.DataFrame(scaler.transform(X), columns=FEATURE_COLS, index=X.index)
    assert_no_leakage(Xs.columns)

    metrics: dict[str, dict] = {}
    importances: dict[str, dict] = {}
    models = {}
    for label, target in (("cpu_peak", TARGET_CPU), ("memory_peak", TARGET_MEM)):
        y = pd.to_numeric(df[target], errors="coerce")
        ok = y.notna().to_numpy()
        m = _regressor().fit(Xs[tr & ok], y[tr & ok])
        metrics[label] = _eval_reg(y[te & ok], m.predict(Xs[te & ok]))
        importances[label] = dict(zip(FEATURE_COLS, map(float, m.feature_importances_)))
        models[label] = m
        print(f"  {label:<12} R2={metrics[label]['R2']:.4f}  MAE={metrics[label]['MAE']:.5f}  "
              f"RMSE={metrics[label]['RMSE']:.5f}")

    y_f = df[TARGET_FAIL].fillna(0).astype(int)
    if y_f[tr].nunique() < 2:
        print("  WARNING: only one failure class in training data - using prior-only classifier.")
        clf = DummyClassifier(strategy="prior").fit(Xs[tr], y_f[tr])
    else:
        clf = RandomForestClassifier(n_estimators=150, max_depth=8, min_samples_leaf=3,
                                     random_state=42, n_jobs=-1).fit(Xs[tr], y_f[tr])
    if y_f[te].nunique() == 2 and hasattr(clf, "feature_importances_"):
        auc = float(roc_auc_score(y_f[te], clf.predict_proba(Xs[te])[:, 1]))
        metrics["failure"] = {"ROC_AUC": auc}
        print(f"  {'failure':<12} ROC-AUC={auc:.4f}")
    else:
        metrics["failure"] = {"ROC_AUC": None}
        print("  failure      ROC-AUC unavailable (single class in test window)")
    if hasattr(clf, "feature_importances_"):
        importances["failure"] = dict(zip(FEATURE_COLS, map(float, clf.feature_importances_)))

    artifact_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(models["cpu_peak"], artifact_dir / "cpu_peak_model.pkl")
    joblib.dump(models["memory_peak"], artifact_dir / "memory_peak_model.pkl")
    joblib.dump(clf, artifact_dir / "failure_model.pkl")
    joblib.dump(scaler, artifact_dir / "scaler.pkl")
    meta = {
        "trained_at": pd.Timestamp.now().isoformat(timespec="seconds"),
        "features": FEATURE_COLS,
        "forbidden_columns": sorted(FORBIDDEN_COLUMNS),
        "leakage_free": True,
        "defaults": defaults,
        "metrics": metrics,
        "feature_importances": importances,
        "n_train": int(tr.sum()), "n_test": int(te.sum()),
        "hyperparameters": {"n_estimators": N_TREES, "max_depth": MAX_DEPTH},
    }
    (artifact_dir / "metadata.json").write_text(json.dumps(meta, indent=2))
    print(f"\nArtifacts saved to {artifact_dir}  ({time.time() - t0:.1f}s)")
    return meta


if __name__ == "__main__":
    train()
