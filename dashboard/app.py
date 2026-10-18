"""Streamlit dashboard for the Cloud Right-Sizing Advisor.

Run:  streamlit run dashboard/app.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from model.recommender import (
    DATA_PATH, SAFETY_BUFFER, TIER_BY_NAME, ArtifactsMissingError, get_engine,
    load_metrics_csv, summarize,
)

st.set_page_config(page_title="Cloud Right-Sizing Advisor", page_icon="📉", layout="wide")

RISK_COLORS = {"LOW": "#16A34A", "MEDIUM": "#D97706", "HIGH": "#DC2626"}
ACTION_COLORS = {"downsize": "#2563EB", "keep": "#6B7280", "upsize": "#DC2626"}


@st.cache_data(show_spinner="Running the model on 30 days of metrics...")
def load(path: str, mtime: float):
    metrics = load_metrics_csv(Path(path))
    metrics["timestamp"] = pd.to_datetime(metrics["timestamp"], utc=True).dt.tz_convert(None)
    return metrics, get_engine().recommend(metrics)


def money(x: float) -> str:
    return f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}"


# ── Load ───────────────────────────────────────────────────────────────────────
st.title("📉 Cloud Right-Sizing Advisor")
st.info("**Advisory only.** This tool never resizes anything. Every recommendation requires "
        "review and approval by your cloud team.", icon="🛡️")

try:
    metrics, recs = load(str(DATA_PATH), os.path.getmtime(DATA_PATH))
except FileNotFoundError:
    st.error("No metrics data found. Run `python scripts/generate_data.py` first.")
    st.stop()
except ArtifactsMissingError as e:
    st.error(f"{e}")
    st.stop()
except ValueError as e:
    st.error(f"Could not process metrics data: {e}")
    st.stop()

# ── Sidebar filters ────────────────────────────────────────────────────────────
st.sidebar.header("Filters")
actions = st.sidebar.multiselect("Action", ["downsize", "keep", "upsize"],
                                 default=["downsize", "keep", "upsize"])
risks = st.sidebar.multiselect("Risk level", ["LOW", "MEDIUM", "HIGH"],
                               default=["LOW", "MEDIUM", "HIGH"])
min_conf = st.sidebar.slider("Minimum confidence", 0, 100, 0)
st.sidebar.caption(f"Safety buffer: **{SAFETY_BUFFER:.0%}** above predicted peak. "
                   "Maximum usage is never a model input (leakage-free).")
if st.sidebar.button("Reload data"):
    st.cache_data.clear()
    st.rerun()

view = recs[recs["action"].isin(actions) & recs["risk_level"].isin(risks) & (recs["confidence"] >= min_conf)]
s = summarize(recs)

# ── KPIs ───────────────────────────────────────────────────────────────────────
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Monthly spend", money(s["current_monthly_spend"]))
c2.metric("Potential monthly savings", money(s["potential_monthly_savings"]),
          f"{s['savings_pct_of_spend']}% of spend")
c3.metric("…of which LOW risk", money(s["low_risk_monthly_savings"]))
c4.metric("VMs to downsize", s["by_action"].get("downsize", 0), f"of {s['vm_count']}")
c5.metric("Avg confidence", f"{s['avg_confidence']:.0f}/100")

tab_over, tab_detail, tab_model = st.tabs(["Overview", "VM detail", "Model"])

# ── Overview ───────────────────────────────────────────────────────────────────
with tab_over:
    if view.empty:
        st.warning("No VMs match the current filters.")
    else:
        left, right = st.columns(2)
        cost = view.melt(id_vars="vm_id", value_vars=["current_monthly_cost", "recommended_monthly_cost"],
                         var_name="Plan", value_name="Monthly cost (USD)")
        cost["Plan"] = cost["Plan"].map({"current_monthly_cost": "Current",
                                         "recommended_monthly_cost": "Recommended"})
        fig = px.bar(cost, x="vm_id", y="Monthly cost (USD)", color="Plan", barmode="group",
                     color_discrete_map={"Current": "#9CA3AF", "Recommended": "#2563EB"},
                     title="Current vs recommended monthly cost")
        fig.update_layout(xaxis_title=None, legend_title=None)
        left.plotly_chart(fig, use_container_width=True)

        util = view.melt(id_vars="vm_id",
                         value_vars=["avg_cpu_util_pct", "predicted_peak_cpu_pct_of_current"],
                         var_name="Metric", value_name="% of current instance")
        util["Metric"] = util["Metric"].map({"avg_cpu_util_pct": "Average CPU",
                                             "predicted_peak_cpu_pct_of_current": "Predicted peak CPU"})
        fig = px.bar(util, x="vm_id", y="% of current instance", color="Metric", barmode="group",
                     color_discrete_map={"Average CPU": "#F59E0B", "Predicted peak CPU": "#7C3AED"},
                     title="CPU: average vs predicted peak (bursty VMs stand out)")
        fig.update_layout(xaxis_title=None, legend_title=None)
        right.plotly_chart(fig, use_container_width=True)

        fig = px.scatter(view, x="confidence", y="failure_risk", color="risk_level", size=view["monthly_savings"].abs() + 10,
                         hover_name="vm_id", color_discrete_map=RISK_COLORS,
                         hover_data={"action": True, "recommended_tier": True, "monthly_savings": ":.0f"},
                         title="Confidence vs failure risk (bubble size = $ impact)")
        fig.update_layout(xaxis_title="Confidence score (0-100)", yaxis_title="Failure risk (%)")
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("Recommendations")
        table = view[["vm_id", "current_tier", "recommended_tier", "action", "monthly_savings",
                      "confidence", "failure_risk", "risk_level", "reason"]].rename(columns={
            "vm_id": "VM", "current_tier": "Current", "recommended_tier": "Recommended",
            "action": "Action", "monthly_savings": "Savings / mo ($)", "confidence": "Confidence",
            "failure_risk": "Failure risk (%)", "risk_level": "Risk", "reason": "Why"})
        st.dataframe(table, hide_index=True, use_container_width=True, column_config={
            "Savings / mo ($)": st.column_config.NumberColumn(format="$%.0f"),
            "Confidence": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f"),
            "Failure risk (%)": st.column_config.NumberColumn(format="%.1f"),
        })
        st.download_button("Download recommendations (CSV)", view.to_csv(index=False),
                           "rightsizing_recommendations.csv", "text/csv")

# ── VM detail ──────────────────────────────────────────────────────────────────
with tab_detail:
    vm = st.selectbox("Select a VM", recs["vm_id"].tolist())
    r = recs[recs["vm_id"] == vm].iloc[0]
    cur, rec = TIER_BY_NAME[r["current_tier"]], TIER_BY_NAME[r["recommended_tier"]]

    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Current tier", f"{cur.name}", f"${cur.monthly_cost:,.0f}/mo", delta_color="off")
    d2.metric("Recommended", f"{rec.name}", f"${rec.monthly_cost:,.0f}/mo", delta_color="off")
    d3.metric("Monthly savings", money(r["monthly_savings"]))
    d4.metric("Action", r["action"].upper())
    e1, e2, e3 = st.columns(3)
    e1.metric("Confidence", f"{r['confidence']:.0f}/100")
    e2.metric("Failure risk", f"{r['failure_risk']:.1f}%")
    e3.metric("Risk level", r["risk_level"])
    st.markdown(f"**Why:** {r['reason']}")
    st.caption("Human review required before any change is made.")

    g = metrics[metrics["vm_id"] == vm].sort_values("timestamp")
    for label, avg_col, max_col, pred, need, cur_cap, rec_cap in (
        ("CPU", "average_usage_cpus", "maximum_usage_cpus", r["predicted_peak_cpu"],
         r["required_cpu_with_buffer"], cur.cpu_fraction, rec.cpu_fraction),
        ("Memory", "average_usage_memory", "maximum_usage_memory", r["predicted_peak_memory"],
         r["required_mem_with_buffer"], cur.mem_fraction, rec.mem_fraction),
    ):
        pct = lambda v: 100 * v / cur_cap     # express everything as % of the CURRENT instance
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=g["timestamp"], y=pct(g[avg_col]), name="Average usage",
                                 line=dict(color="#F59E0B", width=1.5)))
        if max_col in g.columns:
            fig.add_trace(go.Scatter(x=g["timestamp"], y=pct(g[max_col]), name="Observed peak",
                                     line=dict(color="#9CA3AF", width=1)))
        fig.add_hline(y=pct(pred), line=dict(color="#7C3AED", dash="dot"),
                      annotation_text="Predicted peak", annotation_position="top left")
        fig.add_hline(y=pct(need), line=dict(color="#2563EB", dash="dash"),
                      annotation_text=f"Peak + {SAFETY_BUFFER:.0%} buffer", annotation_position="bottom left")
        fig.add_hline(y=pct(rec_cap), line=dict(color="#16A34A"),
                      annotation_text=f"Recommended capacity ({rec.name})", annotation_position="top right")
        fig.add_hline(y=100, line=dict(color="#DC2626"),
                      annotation_text=f"Current capacity ({cur.name})", annotation_position="top right")
        fig.update_layout(title=f"{label} - % of current instance capacity", yaxis_title="% of current capacity",
                          xaxis_title=None, legend=dict(orientation="h", y=-0.2),
                          yaxis_range=[0, max(110, pct(g[avg_col]).max() * 1.1)])
        st.plotly_chart(fig, use_container_width=True)

    cmp = pd.DataFrame({
        "": ["vCPU cores", "Memory (GB)", "Monthly cost"],
        f"Current ({cur.name})": [str(cur.cores), str(cur.mem_gb), f"${cur.monthly_cost:,.0f}"],
        f"Recommended ({rec.name})": [str(rec.cores), str(rec.mem_gb), f"${rec.monthly_cost:,.0f}"],
    })
    st.table(cmp.set_index(""))

# ── Model ──────────────────────────────────────────────────────────────────────
with tab_model:
    eng = get_engine()
    m = eng.meta
    st.markdown(f"Trained **{m['trained_at']}** on {m['n_train']:,} rows, tested on {m['n_test']:,} "
                "later rows (chronological split).")
    st.success("Leakage-free: `maximum_usage_cpus`, `maximum_usage_memory`, `cpu_burst_ratio` and "
               "`cpu_range` are never model inputs (runtime assertion enforced).", icon="✅")
    mt = pd.DataFrame(m["metrics"]).T.rename_axis("Model").reset_index()
    st.dataframe(mt, hide_index=True, use_container_width=True)
    imp = pd.Series(m["feature_importances"]["cpu_peak"]).nlargest(10).sort_values()
    st.plotly_chart(px.bar(imp, orientation="h", title="Top features - peak CPU model",
                           labels={"value": "Importance", "index": ""}).update_layout(showlegend=False),
                    use_container_width=True)
