"""Synthetic demo data generator for the Cloud Right-Sizing Advisor.

Creates 15 over-provisioned VMs x 30 days x 4 six-hour windows (1,800 rows)
and writes data/vm_metrics.csv.

All CPU / memory quantities are expressed as a FRACTION OF THE LARGEST MACHINE
(32 cores / 128 GB), matching the normalisation used in the research paper.

Run:  python scripts/generate_data.py [--seed 42] [--out data/vm_metrics.csv]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "data" / "vm_metrics.csv"

DAYS = 30
WINDOWS_PER_DAY = 4
WINDOW_SECONDS = 24 * 3600 // WINDOWS_PER_DAY

# Instance tiers (cores, GB) normalised against 32 cores / 128 GB.
# (Duplicated from model/recommender.py on purpose so this script is standalone.)
TIER_SPECS = {
    "micro": (1, 2), "small": (2, 4), "medium": (4, 8),
    "large": (8, 16), "xlarge": (16, 32), "2xlarge": (32, 64),
}


def _tier_fracs(name: str) -> tuple[float, float]:
    cores, gb = TIER_SPECS[name]
    return cores / 32, gb / 128


def _vm(vm_id, tier, cpu, mem, peak=(1.3, 1.9), mem_peak=(1.02, 1.10), burst_p=0.0,
        burst=(0.0, 0.0), business_hours_only=False, diurnal=False,
        prio=100, sched=0, ctype=1, noise=0.08):
    return dict(noise=noise, vm_id=vm_id, tier=tier, cpu=cpu, mem=mem, peak=peak, mem_peak=mem_peak,
                burst_p=burst_p, burst=burst, bh_only=business_hours_only,
                diurnal=diurnal, prio=prio, sched=sched, ctype=ctype)


# cpu / mem / burst values are utilisation of the PROVISIONED instance.
VMS = [
    _vm("vm-idle-001", "xlarge", (0.02, 0.03), 0.08, peak=(1.3, 2.0), prio=25, sched=0),
    _vm("vm-idle-002", "xlarge", (0.02, 0.03), 0.09, peak=(1.3, 2.0), prio=25, sched=0),
    _vm("vm-batch-001", "2xlarge", (0.06, 0.08), 0.30, peak=(1.2, 1.6), burst_p=0.10,
        burst=(0.40, 0.60), prio=25, sched=0),
    _vm("vm-batch-002", "2xlarge", (0.06, 0.08), 0.32, peak=(1.2, 1.6), burst_p=0.10,
        burst=(0.40, 0.60), prio=25, sched=0),
    _vm("vm-web-001", "xlarge", (0.12, 0.15), 0.30, diurnal=True, prio=119, sched=3),
    _vm("vm-web-002", "xlarge", (0.12, 0.15), 0.28, diurnal=True, prio=119, sched=3),
    _vm("vm-db-001", "xlarge", (0.44, 0.46), 0.55, peak=(1.1, 1.35), mem_peak=(1.01, 1.05), noise=0.03,
        prio=119, sched=2),
    _vm("vm-db-002", "xlarge", (0.59, 0.61), 0.65, peak=(1.05, 1.20), mem_peak=(1.01, 1.05), noise=0.03,
        prio=119, sched=2),
    _vm("vm-ml-001", "xlarge", (0.65, 0.66), 0.66, peak=(1.01, 1.03), mem_peak=(1.01, 1.03), noise=0.02,
        prio=105, sched=1),
    _vm("vm-ml-002", "xlarge", (0.65, 0.67), 0.66, peak=(1.01, 1.03), mem_peak=(1.01, 1.03), noise=0.02,
        prio=105, sched=1),
    _vm("vm-api-001", "large", (0.18, 0.20), 0.30, peak=(1.25, 1.6), diurnal=True,
        prio=119, sched=3),
    _vm("vm-api-002", "large", (0.18, 0.20), 0.31, peak=(1.25, 1.6), diurnal=True,
        prio=119, sched=3),
    _vm("vm-ci-001", "xlarge", (0.08, 0.09), 0.25, peak=(1.2, 1.6), burst_p=0.12,
        burst=(0.50, 0.60), business_hours_only=True, prio=105, sched=0),
    _vm("vm-cache-001", "large", (0.24, 0.26), 0.65, peak=(1.1, 1.4), mem_peak=(1.01, 1.05),
        prio=119, sched=2),
    _vm("vm-monitor-001", "medium", (0.29, 0.31), 0.35, peak=(1.2, 1.5), prio=105, sched=1),
]


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def generate(seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    end = pd.Timestamp.now().floor("D")
    start = end - pd.Timedelta(days=DAYS)
    stamps = pd.date_range(start, periods=DAYS * WINDOWS_PER_DAY, freq=f"{WINDOW_SECONDS}s")

    rows = []
    for spec in VMS:
        req_cpu, req_mem = _tier_fracs(spec["tier"])
        cpu_base = rng.uniform(*spec["cpu"])
        mem_base = spec["mem"]
        cpi_base = rng.normal(1.2, 0.15)

        for ts in stamps:
            hour = ts.hour
            diurnal = 1 + 0.15 * np.sin(2 * np.pi * (hour - 6) / 24) if spec["diurnal"] else 1.0
            avg_u = max(cpu_base * diurnal * rng.normal(1.0, spec["noise"]), 0.001)

            can_burst = (not spec["bh_only"]) or (9 <= hour < 18 and ts.dayofweek < 5)
            if spec["burst_p"] > 0 and can_burst and rng.random() < spec["burst_p"]:
                peak_u = rng.uniform(*spec["burst"])
                avg_u += 0.15 * (peak_u - avg_u)
            else:
                peak_u = avg_u * rng.uniform(*spec["peak"])
            peak_u = min(max(peak_u, avg_u * 1.02), 0.98)

            mem_avg_u = max(mem_base * rng.normal(1.0, 0.03), 0.005)
            mem_peak_u = min(mem_avg_u * rng.uniform(*spec["mem_peak"]), 0.99)

            avg_cpu, max_cpu = avg_u * req_cpu, peak_u * req_cpu
            avg_mem, max_mem = mem_avg_u * req_mem, mem_peak_u * req_mem

            tail = avg_cpu + rng.uniform(0.4, 0.9) * (max_cpu - avg_cpu)
            dist_mean = avg_cpu * rng.uniform(0.95, 1.0)
            dist_std = (max_cpu - avg_cpu) / rng.uniform(2.5, 3.5) + 1e-6

            # Failure (OOM / throttling-induced) probability rises as peak nears capacity.
            tightness = max(max_cpu / req_cpu, max_mem / req_mem)
            p_fail = 0.02 + 0.6 * _sigmoid(14 * (tightness - 0.9))

            rows.append({
                "vm_id": spec["vm_id"],
                "timestamp": ts.isoformat(),
                "instance_type": spec["tier"],
                "resource_request_cpus": req_cpu,
                "resource_request_memory": req_mem,
                "priority": spec["prio"],
                "scheduling_class": spec["sched"],
                "collection_type": spec["ctype"],
                "average_usage_cpus": avg_cpu,
                "average_usage_memory": avg_mem,
                "maximum_usage_cpus": max_cpu,        # prediction TARGET only
                "maximum_usage_memory": max_mem,      # prediction TARGET only
                "cpu_usage_distribution_mean": dist_mean,
                "cpu_usage_distribution_std": dist_std,
                "tail_cpu_usage_distribution_mean": tail,
                "duration": WINDOW_SECONDS * rng.uniform(0.5, 1.0),
                "cycles_per_instruction": max(rng.normal(cpi_base, 0.1), 0.2),
                "memory_accesses_per_instruction": max(rng.normal(0.05, 0.01), 0.001),
                "failed": int(rng.random() < p_fail),
            })
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    df = generate(args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)

    df["cpu_util_pct"] = 100 * df["average_usage_cpus"] / df["resource_request_cpus"]
    df["peak_util_pct"] = 100 * df["maximum_usage_cpus"] / df["resource_request_cpus"]
    summ = df.groupby(["vm_id", "instance_type"]).agg(
        avg_cpu_util_pct=("cpu_util_pct", "mean"),
        max_cpu_util_pct=("peak_util_pct", "max"),
        failures=("failed", "sum"),
    ).round(1)
    print(f"Wrote {len(df):,} rows for {df['vm_id'].nunique()} VMs -> {args.out}\n")
    print(summ.to_string())


if __name__ == "__main__":
    main()
