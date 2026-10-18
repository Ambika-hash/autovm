"""Generate PNG charts for the trained models (train/test split, accuracy, tiers, risk, savings).

Run:   python -m model.plots            (after python -m model.train)
Saves: artifacts/plots/*.png   (white background, 200 dpi)
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")                      # no display needed
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Patch
from sklearn.metrics import (average_precision_score, confusion_matrix, precision_recall_curve,
                             r2_score, roc_auc_score, roc_curve)

from model.evaluate import tier_of
from model.recommender import ARTIFACT_DIR, PEAK_PERCENTILE, TIERS, RightSizingEngine
from model.train import (DATA_PATH, TARGET_CPU, TARGET_FAIL, TARGET_MEM, TRAIN_FRACTION,
                         build_feature_matrix, engineer_features, load_metrics)

plt.rcParams.update({
    "figure.facecolor": "white", "axes.facecolor": "white",
    "savefig.facecolor": "white", "savefig.edgecolor": "white",
    "axes.spines.top": False, "axes.spines.right": False,
    "font.size": 10, "axes.titleweight": "bold",
})
BLUE, ORANGE, GREEN, RED, AMBER, GRAY = "#2563EB", "#F97316", "#16A34A", "#DC2626", "#D97706", "#9CA3AF"
TIER_NAMES = [t.name for t in TIERS]


def save(fig, out_dir: Path, name: str) -> None:
    fig.tight_layout()
    fig.savefig(out_dir / name, dpi=200, bbox_inches="tight", format="png", facecolor="white", pad_inches=0.1)
    plt.close(fig)
    print(f"  saved {out_dir / name}")


def heatmap(ax, cm: np.ndarray, labels: list[str], title: str) -> None:
    ax.imshow(cm, cmap="Blues")
    ax.set_xticks(range(len(labels)), labels, rotation=30)
    ax.set_yticks(range(len(labels)), labels)
    ax.set_xlabel("Predicted tier")
    ax.set_ylabel("True tier")
    ax.set_title(title)
    thr = cm.max() / 2 if cm.max() else 1
    for i in range(len(labels)):
        for j in range(len(labels)):
            ax.text(j, i, int(cm[i, j]), ha="center", va="center",
                    color="white" if cm[i, j] > thr else "black")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--data", default=str(DATA_PATH))
    ap.add_argument("--out", default=str(ARTIFACT_DIR / "plots"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    eng = RightSizingEngine()
    raw = load_metrics(args.data)
    df = engineer_features(raw)
    X = build_feature_matrix(df, eng.defaults)                    # leakage assertion
    Xs = pd.DataFrame(eng.scaler.transform(X[eng.features]), columns=eng.features, index=X.index)
    cutoff = df["timestamp"].quantile(TRAIN_FRACTION)
    tr, te = (df["timestamp"] <= cutoff).to_numpy(), (df["timestamp"] > cutoff).to_numpy()
    p_cpu, p_mem = eng.cpu_model.predict(Xs), eng.mem_model.predict(Xs)
    classes = list(eng.fail_model.classes_)
    proba = eng.fail_model.predict_proba(Xs)[:, classes.index(1)] if 1 in classes else np.zeros(len(df))
    print(f"Writing charts to {out}")

    # 1. Train / test split -------------------------------------------------------
    day = (df["timestamp"] - df["timestamp"].min()).dt.total_seconds() / 86400
    split_day = day[df["timestamp"] <= cutoff].max()
    end_day = day.max()
    vms = sorted(df["vm_id"].unique())
    fig, ax = plt.subplots(figsize=(10, 6))
    for i, v in enumerate(vms):
        ax.barh(i, split_day, color=BLUE, height=0.7)
        ax.barh(i, end_day - split_day, left=split_day, color=ORANGE, height=0.7)
    ax.axvline(split_day, color="black", ls="--", lw=1)
    ax.set_yticks(range(len(vms)), vms)
    ax.invert_yaxis()
    ax.set_xlabel("Day")
    ax.set_title(f"Chronological train / test split  (train {tr.sum():,} rows, test {te.sum():,} rows)")
    ax.legend(handles=[Patch(color=BLUE, label="Train (first 80% of time)"),
                       Patch(color=ORANGE, label="Test (last 20%, unseen)")], loc="lower left")
    save(fig, out, "01_train_test_split.png")

    # 2. Predicted vs actual (test) ----------------------------------------------
    fig, axes = plt.subplots(1, 2, figsize=(11, 5))
    for ax, (name, y, p) in zip(axes, (("Peak CPU", df[TARGET_CPU], p_cpu), ("Peak memory", df[TARGET_MEM], p_mem))):
        yt, pt = y[te].to_numpy(), p[te]
        ax.scatter(yt, pt, s=12, alpha=0.6, color=BLUE)
        lim = [0, max(yt.max(), pt.max()) * 1.05]
        ax.plot(lim, lim, color=RED, ls="--", lw=1, label="Perfect prediction")
        ax.set_xlim(lim); ax.set_ylim(lim)
        ax.set_xlabel("Actual (fraction of 32-core / 128 GB machine)")
        ax.set_ylabel("Predicted")
        ax.set_title(f"{name} - test set  (R2 = {r2_score(yt, pt):.4f})")
        ax.legend(loc="upper left")
    save(fig, out, "02_predicted_vs_actual.png")

    # 3. Time series for four VM profiles ------------------------------------------
    picks = [v for v in ("vm-batch-001", "vm-web-001", "vm-ci-001", "vm-db-002") if v in vms] or vms[:4]
    fig, axes = plt.subplots(len(picks), 1, figsize=(11, 2.6 * len(picks)), sharex=False)
    axes = np.atleast_1d(axes)
    for ax, v in zip(axes, picks):
        m = te & (df["vm_id"] == v).to_numpy()
        ax.plot(df.loc[m, "timestamp"], df.loc[m, TARGET_CPU], color=BLUE, lw=1.3, label="Actual peak")
        ax.plot(df.loc[m, "timestamp"], p_cpu[m], color=ORANGE, lw=1.3, label="Predicted peak")
        ax.set_title(v, fontsize=10)
        ax.set_ylabel("CPU fraction")
    axes[0].legend(ncol=2, loc="upper right")
    fig.suptitle("Actual vs predicted peak CPU on the test window", fontweight="bold")
    save(fig, out, "03_peak_cpu_timeseries.png")

    # 4. Error distribution ---------------------------------------------------------
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    for ax, (name, y, p) in zip(axes, (("Peak CPU", df[TARGET_CPU], p_cpu), ("Peak memory", df[TARGET_MEM], p_mem))):
        err = 100 * (p[te] - y[te].to_numpy()) / np.maximum(y[te].to_numpy(), 1e-9)
        ax.hist(err, bins=40, color=BLUE, edgecolor="white")
        ax.axvline(0, color=RED, ls="--", lw=1)
        ax.set_xlabel("Prediction error (% of actual; negative = under-predicted)")
        ax.set_ylabel("Windows")
        ax.set_title(f"{name}: mean abs error {np.mean(np.abs(err)):.2f}%")
    save(fig, out, "04_error_distribution.png")

    # 5. Tier confusion matrices ------------------------------------------------------
    t = df.loc[te, ["vm_id", TARGET_CPU, TARGET_MEM]].copy()
    t["p_cpu"], t["p_mem"] = p_cpu[te], p_mem[te]
    t["true"] = [tier_of(c, m) for c, m in zip(t[TARGET_CPU], t[TARGET_MEM])]
    t["pred"] = [tier_of(c, m) for c, m in zip(t["p_cpu"], t["p_mem"])]
    g = t.groupby("vm_id").agg(
        c=(TARGET_CPU, lambda s: np.percentile(s, PEAK_PERCENTILE)), m=(TARGET_MEM, lambda s: np.percentile(s, PEAK_PERCENTILE)),
        pc=("p_cpu", lambda s: np.percentile(s, PEAK_PERCENTILE)), pm=("p_mem", lambda s: np.percentile(s, PEAK_PERCENTILE)))
    g["true"] = [tier_of(c, m) for c, m in zip(g.c, g.m)]
    g["pred"] = [tier_of(c, m) for c, m in zip(g.pc, g.pm)]
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    for ax, d, title in ((axes[0], t, "Window level"), (axes[1], g, f"VM level (p{PEAK_PERCENTILE} peak)")):
        labels = [x for x in TIER_NAMES if x in set(d["true"]) | set(d["pred"])]
        acc = np.mean(d["true"] == d["pred"]) * 100
        heatmap(ax, confusion_matrix(d["true"], d["pred"], labels=labels), labels, f"{title} - accuracy {acc:.1f}%")
    save(fig, out, "05_tier_confusion.png")

    # 6. Failure classifier --------------------------------------------------------------
    y_f = df.loc[te, TARGET_FAIL].fillna(0).astype(int).to_numpy()
    pf = proba[te]
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5))
    if len(set(y_f)) == 2:
        fpr, tpr, _ = roc_curve(y_f, pf)
        axes[0].plot(fpr, tpr, color=BLUE, lw=2, label=f"AUC = {roc_auc_score(y_f, pf):.3f}")
        pr, rc, _ = precision_recall_curve(y_f, pf)
        axes[1].plot(rc, pr, color=ORANGE, lw=2, label=f"AP = {average_precision_score(y_f, pf):.3f}")
    else:
        axes[0].text(0.5, 0.5, "Only one class in test window", ha="center", transform=axes[0].transAxes)
    axes[0].plot([0, 1], [0, 1], color=GRAY, ls="--"); axes[0].legend(loc="lower right")
    axes[0].set(xlabel="False positive rate", ylabel="True positive rate", title="ROC curve")
    axes[1].axhline(y_f.mean(), color=GRAY, ls="--", label=f"Base rate {y_f.mean():.3f}"); axes[1].legend()
    axes[1].set(xlabel="Recall", ylabel="Precision", title="Precision-recall curve")
    axes[2].hist(pf[y_f == 0], bins=30, alpha=0.7, color=BLUE, label=f"No failure (n={int((y_f == 0).sum())})")
    if (y_f == 1).any():
        axes[2].hist(pf[y_f == 1], bins=30, alpha=0.8, color=RED, label=f"Failure (n={int((y_f == 1).sum())})")
    axes[2].set(xlabel="Predicted failure probability", ylabel="Windows", title="Probability by true outcome")
    axes[2].set_yscale("log"); axes[2].legend()
    save(fig, out, "06_failure_classifier.png")

    # 7. Feature importance ---------------------------------------------------------------
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    for ax, key, title in ((axes[0], "cpu_peak", "Peak CPU model"), (axes[1], "memory_peak", "Peak memory model")):
        imp = pd.Series(eng.meta["feature_importances"][key]).nlargest(10).sort_values()
        ax.barh(imp.index.str.replace("_", " "), imp.values, color=BLUE)
        ax.set_title(f"Top features - {title}"); ax.set_xlabel("Importance")
    save(fig, out, "07_feature_importance.png")

    # 8. Recommendations: cost + risk ------------------------------------------------------
    recs = eng.recommend(raw)
    risk_c = {"LOW": GREEN, "MEDIUM": AMBER, "HIGH": RED}
    fig, ax = plt.subplots(figsize=(12, 5.5))
    x = np.arange(len(recs)); w = 0.4
    ax.bar(x - w / 2, recs["current_monthly_cost"], w, color=GRAY, label="Current")
    ax.bar(x + w / 2, recs["recommended_monthly_cost"], w, color=[risk_c[r] for r in recs["risk_level"]])
    for i, r in recs.iterrows():
        if r["monthly_savings"] != 0:
            ax.text(i + w / 2, r["recommended_monthly_cost"] + 6, f"{r['monthly_savings']:+.0f}", ha="center", fontsize=8)
    ax.set_xticks(x, recs["vm_id"], rotation=45, ha="right")
    ax.set_ylabel("USD / month")
    s = recs.loc[recs["action"] == "downsize", "monthly_savings"].sum()
    ax.set_title(f"Current vs recommended cost  (potential saving ${s:,.0f}/month)")
    ax.legend(handles=[Patch(color=GRAY, label="Current"), Patch(color=GREEN, label="Recommended - LOW risk"),
                       Patch(color=AMBER, label="Recommended - MEDIUM risk"), Patch(color=RED, label="Recommended - HIGH risk")])
    save(fig, out, "08_cost_savings.png")
    print("Done.")


if __name__ == "__main__":
    main()