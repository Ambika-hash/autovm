"""
autovm/scripts/workload_clustering.py

Groups VMs into behavior profiles (idle / steady / bursty / seasonal) using
K-Means, BEFORE the Random Forest regressors/classifier run.

Placement: this file lives in autovm/scripts/, next to generate_data.py,
since it's a standalone script that reads a data file and writes a data file
-- the same role generate_data.py plays.

Usage (run from the autovm-master/ or autovm/ root, matching your other
scripts):
    python -m scripts.workload_clustering --csv data/vm_metrics.csv --k 4 --out data/vm_clusters.csv

Defaults already point at your actual files (data/vm_metrics.csv ->
data/vm_clusters.csv), so you can also just run:
    python -m scripts.workload_clustering
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import silhouette_score

ROOT = Path(__file__).resolve().parents[1]  # autovm/
DEFAULT_IN = ROOT / "data" / "vm_metrics.csv"  # matches your Explorer tree
DEFAULT_OUT = ROOT / "data" / "vm_clusters.csv"

FEATURE_COLUMNS_PRIORITY = [
    "burst_ratio",
    "cv_over_time",
    "std_cpu",
    "idle_fraction",
    "tail_ratio",
    "mem_burst_ratio",
]

SUGGESTED_BUFFERS = {
    "idle": 0.20,
    "steady": 0.30,
    "bursty": 0.45,
    "seasonal/irregular": 0.50,
}


def build_vm_profile_features(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse many time-window rows per VM into ONE behavior-profile row per VM."""
    required = [
        "vm_id",
        "average_usage_cpus",
        "maximum_usage_cpus",
        "cpu_usage_distribution_std",
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    has_tail = "tail_cpu_usage_distribution_mean" in df.columns
    has_mem = {"average_usage_memory", "maximum_usage_memory"}.issubset(df.columns)

    rows = []
    for vm_id, g in df.groupby("vm_id"):
        avg_cpu = g["average_usage_cpus"].mean()
        max_cpu = g["maximum_usage_cpus"].max()
        std_cpu = g["cpu_usage_distribution_std"].mean()

        burst_ratio = max_cpu / avg_cpu if avg_cpu > 0 else 0.0
        cv_over_time = (
            g["average_usage_cpus"].std() / g["average_usage_cpus"].mean()
            if g["average_usage_cpus"].mean() > 0
            else 0.0
        )
        tail_ratio = np.nan
        if has_tail:
            tail_mean = g["tail_cpu_usage_distribution_mean"].mean()
            tail_ratio = tail_mean / avg_cpu if avg_cpu > 0 else 0.0
        idle_fraction = (g["average_usage_cpus"] < 0.05).mean()

        row = {
            "vm_id": vm_id,
            "avg_cpu": avg_cpu,
            "burst_ratio": burst_ratio,
            "cv_over_time": cv_over_time,
            "std_cpu": std_cpu,
            "idle_fraction": idle_fraction,
            "n_windows": len(g),
        }
        if has_tail:
            row["tail_ratio"] = tail_ratio
        if has_mem:
            avg_mem = g["average_usage_memory"].mean()
            max_mem = g["maximum_usage_memory"].max()
            row["mem_burst_ratio"] = max_mem / avg_mem if avg_mem > 0 else 0.0
        rows.append(row)

    return pd.DataFrame(rows)


def cluster_vms(profile_df: pd.DataFrame, k: int = 4, random_state: int = 42):
    feature_cols = [c for c in FEATURE_COLUMNS_PRIORITY if c in profile_df.columns]
    X = profile_df[feature_cols].fillna(0.0).to_numpy()

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    n_samples = X_scaled.shape[0]
    if k >= n_samples:
        raise ValueError(
            f"k={k} must be smaller than the number of VMs ({n_samples}). "
            f"Reduce --k or provide more VMs."
        )

    kmeans = KMeans(n_clusters=k, random_state=random_state, n_init=10)
    labels = kmeans.fit_predict(X_scaled)

    profile_df = profile_df.copy()
    profile_df["cluster"] = labels

    sil = silhouette_score(X_scaled, labels) if 1 < k < n_samples else float("nan")
    return profile_df, kmeans, scaler, feature_cols, sil


def name_clusters(profile_df: pd.DataFrame):
    """Maps numeric cluster IDs to readable labels (idle/steady/bursty/seasonal)."""
    summary = profile_df.groupby("cluster")[
        ["burst_ratio", "idle_fraction", "cv_over_time"]
    ].mean()
    labels = {}
    for cluster_id, row in summary.iterrows():
        if row["idle_fraction"] > 0.7:
            labels[cluster_id] = "idle"
        elif row["burst_ratio"] > 4:
            labels[cluster_id] = "bursty"
        elif row["cv_over_time"] > 0.5:
            labels[cluster_id] = "seasonal/irregular"
        else:
            labels[cluster_id] = "steady"

    profile_df = profile_df.copy()
    profile_df["cluster_label"] = profile_df["cluster"].map(labels)
    return profile_df, labels


def main():
    parser = argparse.ArgumentParser(description="Cluster VMs into behavior profiles")
    parser.add_argument(
        "--csv", default=str(DEFAULT_IN), help="Path to your metrics CSV"
    )
    parser.add_argument("--k", type=int, default=4, help="Number of clusters")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Output CSV path")
    args = parser.parse_args()

    df = pd.read_csv(args.csv)

    profile_df = build_vm_profile_features(df)
    clustered_df, kmeans, scaler, feature_cols, sil = cluster_vms(profile_df, k=args.k)
    clustered_df, cluster_names = name_clusters(clustered_df)

    clustered_df["suggested_safety_buffer"] = clustered_df["cluster_label"].map(
        SUGGESTED_BUFFERS
    )

    print(f"Features used for clustering: {feature_cols}")
    print(f"Silhouette score (higher = better separated, range -1 to 1): {sil:.3f}")
    print()
    print("Cluster -> behavior label mapping:")
    for cid, name in cluster_names.items():
        count = (clustered_df["cluster"] == cid).sum()
        print(f"  cluster {cid}: {name}  ({count} VMs)")
    print()
    print(
        clustered_df[
            [
                "vm_id",
                "cluster_label",
                "burst_ratio",
                "idle_fraction",
                "suggested_safety_buffer",
            ]
        ].to_string(index=False)
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    clustered_df.to_csv(out_path, index=False)
    print(f"\nSaved full output to {out_path}")


if __name__ == "__main__":
    main()
