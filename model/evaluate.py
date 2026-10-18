"""Evaluate the trained models on the held-out (chronological) test window.

Reports
  1. Regression (peak CPU, peak memory): MAE, RMSE, R2, MAPE, % within 10%, under-prediction rate
  2. Failure classifier: accuracy, balanced accuracy, precision, recall, F1, ROC-AUC, PR-AUC,
     confusion matrix at several decision thresholds (+ the 'always predict no failure' baseline)
  3. Instance-tier accuracy (what actually matters for right-sizing): accuracy, precision, recall,
     F1 per tier, confusion matrix, and the 'unsafe' rate (tier smaller than truly needed),
     at window level and VM level

Run:   python -m model.evaluate            (after python -m model.train)
Saves: artifacts/evaluation_report.json
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd
from sklearn.metrics import (accuracy_score, average_precision_score, balanced_accuracy_score,
                             classification_report, confusion_matrix, f1_score,
                             mean_absolute_error, mean_squared_error, precision_score,
                             r2_score, recall_score, roc_auc_score)

from model.recommender import (ARTIFACT_DIR, PEAK_PERCENTILE, SAFETY_BUFFER, TIER_INDEX, TIERS,
                               RightSizingEngine, smallest_fitting_tier)
from model.train import (DATA_PATH, TARGET_CPU, TARGET_FAIL, TARGET_MEM, TRAIN_FRACTION,
                         build_feature_matrix, engineer_features, load_metrics)

TIER_NAMES = [t.name for t in TIERS]
FAIL_THRESHOLDS = (0.5, 0.2, 0.1)


def hr(title: str) -> None:
    print("\n" + "=" * 70 + f"\n{title}\n" + "=" * 70)


def regression_report(y_true, y_pred) -> dict:
    y_true, y_pred = np.asarray(y_true, float), np.asarray(y_pred, float)
    err = y_pred - y_true
    return {
        "MAE": float(mean_absolute_error(y_true, y_pred)),
        "RMSE": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        "R2": float(r2_score(y_true, y_pred)),
        "MAPE_%": float(np.mean(np.abs(err) / np.maximum(y_true, 1e-9)) * 100),
        "within_10pct_%": float(np.mean(np.abs(err) <= 0.10 * y_true) * 100),
        "under_prediction_rate_%": float(np.mean(err < 0) * 100),
        "mean_under_prediction_%": float(np.mean(np.abs(err[err < 0]) / y_true[err < 0]) * 100)
        if (err < 0).any() else 0.0,
    }


def classifier_report(y_true, proba) -> dict:
    out = {"positives": int(y_true.sum()), "n": int(len(y_true)),
           "base_rate_%": float(y_true.mean() * 100),
           "majority_baseline_accuracy_%": float((1 - y_true.mean()) * 100)}
    two_classes = y_true.nunique() == 2
    out["ROC_AUC"] = float(roc_auc_score(y_true, proba)) if two_classes else None
    out["PR_AUC"] = float(average_precision_score(y_true, proba)) if two_classes else None
    out["thresholds"] = {}
    for th in FAIL_THRESHOLDS:
        pred = (proba >= th).astype(int)
        tn, fp, fn, tp = confusion_matrix(y_true, pred, labels=[0, 1]).ravel()
        out["thresholds"][str(th)] = {
            "accuracy": float(accuracy_score(y_true, pred)),
            "balanced_accuracy": float(balanced_accuracy_score(y_true, pred)),
            "precision": float(precision_score(y_true, pred, zero_division=0)),
            "recall": float(recall_score(y_true, pred, zero_division=0)),
            "f1": float(f1_score(y_true, pred, zero_division=0)),
            "TN": int(tn), "FP": int(fp), "FN": int(fn), "TP": int(tp),
        }
    return out


def tier_of(cpu_peak: float, mem_peak: float) -> str:
    return smallest_fitting_tier(cpu_peak * (1 + SAFETY_BUFFER), mem_peak * (1 + SAFETY_BUFFER))[0].name


def tier_report(true_tiers, pred_tiers) -> dict:
    labels = [t for t in TIER_NAMES if t in set(true_tiers) | set(pred_tiers)]
    true_idx = np.array([TIER_INDEX[t] for t in true_tiers])
    pred_idx = np.array([TIER_INDEX[t] for t in pred_tiers])
    return {
        "n": len(true_tiers),
        "accuracy": float(accuracy_score(true_tiers, pred_tiers)),
        "within_one_tier_%": float(np.mean(np.abs(true_idx - pred_idx) <= 1) * 100),
        "precision_macro": float(precision_score(true_tiers, pred_tiers, labels=labels, average="macro", zero_division=0)),
        "recall_macro": float(recall_score(true_tiers, pred_tiers, labels=labels, average="macro", zero_division=0)),
        "f1_macro": float(f1_score(true_tiers, pred_tiers, labels=labels, average="macro", zero_division=0)),
        "precision_weighted": float(precision_score(true_tiers, pred_tiers, labels=labels, average="weighted", zero_division=0)),
        "recall_weighted": float(recall_score(true_tiers, pred_tiers, labels=labels, average="weighted", zero_division=0)),
        # unsafe = predicted tier is SMALLER than what the real peak needed (risk of throttling / OOM)
        "unsafe_%": float(np.mean(pred_idx < true_idx) * 100),
        "wasteful_%": float(np.mean(pred_idx > true_idx) * 100),
        "labels": labels,
        "confusion": confusion_matrix(true_tiers, pred_tiers, labels=labels).tolist(),
        "per_tier": classification_report(true_tiers, pred_tiers, labels=labels,
                                          output_dict=True, zero_division=0),
    }


def print_tier_report(name: str, rep: dict, true_tiers, pred_tiers) -> None:
    print(f"\n{name}  (n={rep['n']})")
    print(f"  accuracy           {rep['accuracy']:.3f}     within one tier  {rep['within_one_tier_%']:.1f}%")
    print(f"  precision (macro)  {rep['precision_macro']:.3f}     recall (macro)   {rep['recall_macro']:.3f}"
          f"     F1 (macro) {rep['f1_macro']:.3f}")
    print(f"  UNSAFE (tier too small) {rep['unsafe_%']:.1f}%    wasteful (tier too big) {rep['wasteful_%']:.1f}%")
    print("  confusion matrix (rows = true tier, cols = predicted tier):")
    cm = pd.DataFrame(rep["confusion"], index=rep["labels"], columns=rep["labels"])
    print("    " + cm.to_string().replace("\n", "\n    "))
    print("  per-tier precision / recall / F1 / support:")
    for t in rep["labels"]:
        r = rep["per_tier"][t]
        print(f"    {t:<8} {r['precision']:.3f}  {r['recall']:.3f}  {r['f1-score']:.3f}  {int(r['support'])}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--data", default=str(DATA_PATH))
    args = ap.parse_args()

    eng = RightSizingEngine()
    df = engineer_features(load_metrics(args.data))
    X = build_feature_matrix(df, eng.defaults)                    # leakage assertion runs here
    Xs = pd.DataFrame(eng.scaler.transform(X[eng.features]), columns=eng.features, index=X.index)

    cutoff = df["timestamp"].quantile(TRAIN_FRACTION)             # same split as training
    tr, te = (df["timestamp"] <= cutoff).to_numpy(), (df["timestamp"] > cutoff).to_numpy()
    print(f"Evaluation data: train={tr.sum():,} rows (<= {cutoff:%Y-%m-%d %H:%M}), test={te.sum():,} rows")

    report: dict = {"split": {"train_rows": int(tr.sum()), "test_rows": int(te.sum())}}

    # ── 1. Regression ──────────────────────────────────────────────────────────
    hr("1. REGRESSION - peak CPU and peak memory")
    preds = {}
    for label, model, target in (("cpu_peak", eng.cpu_model, TARGET_CPU),
                                 ("memory_peak", eng.mem_model, TARGET_MEM)):
        p = model.predict(Xs)
        preds[label] = p
        report[label] = {"train": regression_report(df.loc[tr, target], p[tr]),
                         "test": regression_report(df.loc[te, target], p[te])}
        print(f"\n{label}")
        print(f"  {'metric':<26}{'train':>12}{'test':>12}")
        for k in report[label]["test"]:
            print(f"  {k:<26}{report[label]['train'][k]:>12.5f}{report[label]['test'][k]:>12.5f}")
        gap = report[label]["train"]["R2"] - report[label]["test"]["R2"]
        print(f"  -> train-test R2 gap {gap:+.4f} ({'possible overfitting' if gap > 0.05 else 'looks healthy'})")

    # ── 2. Failure classifier ──────────────────────────────────────────────────
    hr("2. CLASSIFICATION - job failure")
    y_f = df[TARGET_FAIL].fillna(0).astype(int)
    classes = list(eng.fail_model.classes_)
    proba = eng.fail_model.predict_proba(Xs)[:, classes.index(1)] if 1 in classes else np.zeros(len(df))
    report["failure"] = classifier_report(y_f[te].reset_index(drop=True), proba[te])
    f = report["failure"]
    print(f"Test rows: {f['n']}  failures: {f['positives']} ({f['base_rate_%']:.1f}%)")
    print(f"'Always predict no failure' baseline accuracy: {f['majority_baseline_accuracy_%']:.1f}% "
          "(accuracy alone is misleading for rare events)")
    print(f"ROC-AUC: {f['ROC_AUC'] if f['ROC_AUC'] is None else round(f['ROC_AUC'], 3)}    "
          f"PR-AUC: {f['PR_AUC'] if f['PR_AUC'] is None else round(f['PR_AUC'], 3)}")
    print(f"\n  {'threshold':<10}{'accuracy':>9}{'bal.acc':>9}{'precision':>10}{'recall':>8}{'F1':>7}"
          f"{'TN':>6}{'FP':>5}{'FN':>5}{'TP':>5}")
    for th, r in f["thresholds"].items():
        print(f"  {th:<10}{r['accuracy']:>9.3f}{r['balanced_accuracy']:>9.3f}{r['precision']:>10.3f}"
              f"{r['recall']:>8.3f}{r['f1']:>7.3f}{r['TN']:>6}{r['FP']:>5}{r['FN']:>5}{r['TP']:>5}")

    # ── 3. Instance-tier accuracy ──────────────────────────────────────────────
    hr(f"3. INSTANCE-TIER ACCURACY (tier needed for peak x {1 + SAFETY_BUFFER:.2f})")
    t_df = df.loc[te, ["vm_id", TARGET_CPU, TARGET_MEM]].copy()
    t_df["pred_cpu"], t_df["pred_mem"] = preds["cpu_peak"][te], preds["memory_peak"][te]
    t_df["true_tier"] = [tier_of(c, m) for c, m in zip(t_df[TARGET_CPU], t_df[TARGET_MEM])]
    t_df["pred_tier"] = [tier_of(c, m) for c, m in zip(t_df["pred_cpu"], t_df["pred_mem"])]

    report["tier_window_level"] = tier_report(t_df["true_tier"].tolist(), t_df["pred_tier"].tolist())
    print_tier_report("Window level (every 6-hour window)", report["tier_window_level"],
                      t_df["true_tier"], t_df["pred_tier"])

    vm = t_df.groupby("vm_id").agg(
        true_cpu=(TARGET_CPU, lambda s: np.percentile(s, PEAK_PERCENTILE)),
        true_mem=(TARGET_MEM, lambda s: np.percentile(s, PEAK_PERCENTILE)),
        pred_cpu=("pred_cpu", lambda s: np.percentile(s, PEAK_PERCENTILE)),
        pred_mem=("pred_mem", lambda s: np.percentile(s, PEAK_PERCENTILE)))
    vm["true_tier"] = [tier_of(c, m) for c, m in zip(vm.true_cpu, vm.true_mem)]
    vm["pred_tier"] = [tier_of(c, m) for c, m in zip(vm.pred_cpu, vm.pred_mem)]
    report["tier_vm_level"] = tier_report(vm["true_tier"].tolist(), vm["pred_tier"].tolist())
    print_tier_report(f"VM level (p{PEAK_PERCENTILE} peak per VM, as the recommender uses)",
                      report["tier_vm_level"], vm["true_tier"], vm["pred_tier"])
    print("\n  per-VM detail:")
    print("    " + vm[["true_tier", "pred_tier"]].assign(
        match=lambda d: np.where(d.true_tier == d.pred_tier, "ok", "MISMATCH")
    ).to_string().replace("\n", "\n    "))

    out = ARTIFACT_DIR / "evaluation_report.json"
    out.write_text(json.dumps(report, indent=2))
    print(f"\nFull report saved to {out}")


if __name__ == "__main__":
    main()