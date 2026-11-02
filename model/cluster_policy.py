"""
autovm/model/cluster_policy.py

Integration layer: wires the K-Means output (data/vm_clusters.csv) into
recommender.py / train.py.

Placement: this file lives in autovm/model/, next to recommender.py and
train.py, so it's imported the same way as your other model modules:
    from model.cluster_policy import ClusterPolicy

Run order for your pipeline:
    1. python -m scripts.workload_clustering   (produces data/vm_clusters.csv)
    2. python -m model.train                   (your existing training)
    3. python -m model.recommender             (now cluster-aware)
"""

from pathlib import Path
import pandas as pd

# Fallback used for any VM not found in the cluster table (e.g. a brand new
# VM with no history yet, or if clustering hasn't been re-run recently).
# Matches the engine's current fixed constant, so nothing breaks if a VM
# is missing from the cluster assignment.
DEFAULT_SAFETY_BUFFER = 0.30
DEFAULT_CLUSTER_LABEL = "unknown"

# Per-cluster weighting adjustment for the confidence formula.
# Original formula: confidence = 100 * (0.5*A + 0.3*R + 0.2*C)
# For bursty/seasonal VMs, tree agreement (A) is naturally noisier, so we
# lean a little more on model quality (R) and coverage (C) instead of
# punishing them twice for being inherently harder to predict.
CLUSTER_CONFIDENCE_WEIGHTS = {
    "idle": {"A": 0.50, "R": 0.30, "C": 0.20},  # unchanged, easy case
    "steady": {"A": 0.50, "R": 0.30, "C": 0.20},  # unchanged, original default
    "bursty": {"A": 0.40, "R": 0.35, "C": 0.25},  # trust agreement less
    "seasonal/irregular": {"A": 0.35, "R": 0.35, "C": 0.30},  # trust coverage more
    "unknown": {"A": 0.50, "R": 0.30, "C": 0.20},
}


class ClusterPolicy:
    """
    Loads data/vm_clusters.csv once and exposes fast per-VM lookups.
    Instantiate this ONCE at engine startup (RightSizingEngine.__init__
    already does this), not per-request.
    """

    def __init__(self, cluster_csv_path: Path | str = "data/vm_clusters.csv"):
        path = Path(cluster_csv_path)
        if not path.exists():
            raise FileNotFoundError(
                f"{path} not found. Run: python -m scripts.workload_clustering"
            )
        df = pd.read_csv(path)
        # index by vm_id for O(1) lookups instead of scanning the dataframe
        self._by_vm = df.set_index("vm_id")[
            ["cluster_label", "suggested_safety_buffer"]
        ].to_dict("index")

    def get_safety_buffer(self, vm_id: str) -> float:
        """
        Drop-in replacement for the fixed SAFETY_BUFFER = 0.30.
        Usage in recommender.py:
            buffer = self.cluster_policy.get_safety_buffer(vm_id)
            need_cpu = peak_cpu * (1 + buffer)     # was: peak_cpu * 1.30
        """
        entry = self._by_vm.get(vm_id)
        if entry is None:
            return DEFAULT_SAFETY_BUFFER
        return float(entry["suggested_safety_buffer"])

    def get_cluster_label(self, vm_id: str) -> str:
        entry = self._by_vm.get(vm_id)
        if entry is None:
            return DEFAULT_CLUSTER_LABEL
        return entry["cluster_label"]

    def get_confidence_weights(self, vm_id: str) -> dict:
        """
        Drop-in replacement for the fixed 0.5/0.3/0.2 weights.
        Usage in recommender.py:
            w = self.cluster_policy.get_confidence_weights(vm_id)
            confidence = 100 * (w["A"]*A + w["R"]*R + w["C"]*C)
        """
        label = self.get_cluster_label(vm_id)
        return CLUSTER_CONFIDENCE_WEIGHTS.get(
            label, CLUSTER_CONFIDENCE_WEIGHTS["unknown"]
        )


if __name__ == "__main__":
    # quick manual check: python -m model.cluster_policy
    policy = ClusterPolicy("data/vm_clusters.csv")
    print("Loaded cluster policy for", len(policy._by_vm), "VMs")
