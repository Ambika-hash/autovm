# # from __future__ import annotations

# # import os
# # import sys
# # from pathlib import Path

# # ROOT = Path(__file__).resolve().parents[1]
# # sys.path.insert(0, str(ROOT))

# # import pandas as pd
# # import plotly.express as px
# # import plotly.graph_objects as go
# # import streamlit as st
# # from model.recommender import (
# #     DATA_PATH,
# #     SAFETY_BUFFER,
# #     TIER_BY_NAME,
# #     ArtifactsMissingError,
# #     get_engine,
# #     load_metrics_csv,
# #     summarize,
# # )

# # st.set_page_config(
# #     page_title="Cloud Right-Sizing Advisor", page_icon="~", layout="wide"
# # )

# # RISK_COLORS = {"LOW": "#16A34A", "MEDIUM": "#D97706", "HIGH": "#DC2626"}
# # ACTION_COLORS = {"downsize": "#2563EB", "keep": "#6B7280", "upsize": "#DC2626"}


# # @st.cache_data(show_spinner="Running the model on 30 days of metrics...")
# # def load(path: str, mtime: float):
# #     metrics = load_metrics_csv(Path(path))
# #     metrics["timestamp"] = pd.to_datetime(metrics["timestamp"], utc=True).dt.tz_convert(
# #         None
# #     )
# #     return metrics, get_engine().recommend(metrics)


# # def money(x: float) -> str:
# #     return f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}"


# # # ── Load ───────────────────────────────────────────────────────────────────────
# # st.title("Cloud Right-Sizing Advisor")
# # st.info(
# #     "**Advisory only.** This tool never resizes anything. Every recommendation requires "
# #     "review and approval by your cloud team.",
# #     icon="",
# # )

# # try:
# #     metrics, recs = load(str(DATA_PATH), os.path.getmtime(DATA_PATH))
# # except FileNotFoundError:
# #     st.error("No metrics data found. Run `python scripts/generate_data.py` first.")
# #     st.stop()
# # except ArtifactsMissingError as e:
# #     st.error(f"{e}")
# #     st.stop()
# # except ValueError as e:
# #     st.error(f"Could not process metrics data: {e}")
# #     st.stop()

# # # ── Sidebar filters ────────────────────────────────────────────────────────────
# # st.sidebar.header("Filters")
# # actions = st.sidebar.multiselect(
# #     "Action", ["downsize", "keep", "upsize"], default=["downsize", "keep", "upsize"]
# # )
# # risks = st.sidebar.multiselect(
# #     "Risk level", ["LOW", "MEDIUM", "HIGH"], default=["LOW", "MEDIUM", "HIGH"]
# # )
# # min_conf = st.sidebar.slider("Minimum confidence", 0, 100, 0)
# # st.sidebar.caption(
# #     f"Safety buffer: **{SAFETY_BUFFER:.0%}** above predicted peak. "
# #     "Maximum usage is never a model input (leakage-free)."
# # )
# # if st.sidebar.button("Reload data"):
# #     st.cache_data.clear()
# #     st.rerun()

# # view = recs[
# #     recs["action"].isin(actions)
# #     & recs["risk_level"].isin(risks)
# #     & (recs["confidence"] >= min_conf)
# # ]
# # s = summarize(recs)

# # # ── KPIs ───────────────────────────────────────────────────────────────────────
# # c1, c2, c3, c4, c5 = st.columns(5)
# # c1.metric("Monthly spend", money(s["current_monthly_spend"]))
# # c2.metric(
# #     "Net monthly savings",
# #     money(s["potential_monthly_savings"]),
# #     f"{s['savings_pct_of_spend']}% of spend",
# # )
# # c3.metric("LOW-risk downsize savings", money(s["low_risk_monthly_savings"]))
# # c4.metric("VMs to downsize", s["by_action"].get("downsize", 0), f"of {s['vm_count']}")
# # c5.metric("Avg confidence", f"{s['avg_confidence']:.0f}/100")

# # tab_over, tab_detail, tab_model = st.tabs(["Overview", "VM detail", "Model"])

# # # ── Overview ───────────────────────────────────────────────────────────────────
# # with tab_over:
# #     if view.empty:
# #         st.warning("No VMs match the current filters.")
# #     else:
# #         left, right = st.columns(2)
# #         cost = view.melt(
# #             id_vars="vm_id",
# #             value_vars=["current_monthly_cost", "recommended_monthly_cost"],
# #             var_name="Plan",
# #             value_name="Monthly cost (USD)",
# #         )
# #         cost["Plan"] = cost["Plan"].map(
# #             {
# #                 "current_monthly_cost": "Current",
# #                 "recommended_monthly_cost": "Recommended",
# #             }
# #         )
# #         fig = px.bar(
# #             cost,
# #             x="vm_id",
# #             y="Monthly cost (USD)",
# #             color="Plan",
# #             barmode="group",
# #             color_discrete_map={"Current": "#9CA3AF", "Recommended": "#2563EB"},
# #             title="Current vs recommended monthly cost",
# #         )
# #         fig.update_layout(xaxis_title=None, legend_title=None)
# #         left.plotly_chart(fig, use_container_width=True)

# #         util = view.melt(
# #             id_vars="vm_id",
# #             value_vars=["avg_cpu_util_pct", "predicted_peak_cpu_pct_of_current"],
# #             var_name="Metric",
# #             value_name="% of current instance",
# #         )
# #         util["Metric"] = util["Metric"].map(
# #             {
# #                 "avg_cpu_util_pct": "Average CPU",
# #                 "predicted_peak_cpu_pct_of_current": "Predicted peak CPU",
# #             }
# #         )
# #         fig = px.bar(
# #             util,
# #             x="vm_id",
# #             y="% of current instance",
# #             color="Metric",
# #             barmode="group",
# #             color_discrete_map={
# #                 "Average CPU": "#F59E0B",
# #                 "Predicted peak CPU": "#7C3AED",
# #             },
# #             title="CPU: average vs predicted peak (bursty VMs stand out)",
# #         )
# #         fig.update_layout(xaxis_title=None, legend_title=None)
# #         right.plotly_chart(fig, use_container_width=True)

# #         fig = px.scatter(
# #             view,
# #             x="confidence",
# #             y="failure_risk",
# #             color="risk_level",
# #             size=view["monthly_savings"].abs() + 10,
# #             hover_name="vm_id",
# #             color_discrete_map=RISK_COLORS,
# #             hover_data={
# #                 "action": True,
# #                 "recommended_tier": True,
# #                 "monthly_savings": ":.0f",
# #             },
# #             title="Confidence vs failure risk (bubble size = $ impact)",
# #         )
# #         fig.update_layout(
# #             xaxis_title="Confidence score (0-100)", yaxis_title="Failure risk (%)"
# #         )
# #         st.plotly_chart(fig, use_container_width=True)

# #         st.subheader("Recommendations")
# #         table = view[
# #             [
# #                 "vm_id",
# #                 "current_tier",
# #                 "recommended_tier",
# #                 "action",
# #                 "monthly_savings",
# #                 "confidence",
# #                 "failure_risk",
# #                 "risk_level",
# #                 "reason",
# #             ]
# #         ].rename(
# #             columns={
# #                 "vm_id": "VM",
# #                 "current_tier": "Current",
# #                 "recommended_tier": "Recommended",
# #                 "action": "Action",
# #                 "monthly_savings": "Savings / mo ($)",
# #                 "confidence": "Confidence",
# #                 "failure_risk": "Failure risk (%)",
# #                 "risk_level": "Risk",
# #                 "reason": "Why",
# #             }
# #         )
# #         st.dataframe(
# #             table,
# #             hide_index=True,
# #             use_container_width=True,
# #             column_config={
# #                 "Savings / mo ($)": st.column_config.NumberColumn(format="$%.0f"),
# #                 "Confidence": st.column_config.ProgressColumn(
# #                     min_value=0, max_value=100, format="%.0f"
# #                 ),
# #                 "Failure risk (%)": st.column_config.NumberColumn(format="%.1f"),
# #             },
# #         )
# #         st.download_button(
# #             "Download recommendations (CSV)",
# #             view.to_csv(index=False),
# #             "rightsizing_recommendations.csv",
# #             "text/csv",
# #         )

# # # ── VM detail ──────────────────────────────────────────────────────────────────
# # with tab_detail:
# #     vm = st.selectbox("Select a VM", recs["vm_id"].tolist())
# #     r = recs[recs["vm_id"] == vm].iloc[0]
# #     cur, rec = TIER_BY_NAME[r["current_tier"]], TIER_BY_NAME[r["recommended_tier"]]

# #     d1, d2, d3, d4 = st.columns(4)
# #     d1.metric(
# #         "Current tier", f"{cur.name}", f"${cur.monthly_cost:,.0f}/mo", delta_color="off"
# #     )
# #     d2.metric(
# #         "Recommended", f"{rec.name}", f"${rec.monthly_cost:,.0f}/mo", delta_color="off"
# #     )
# #     d3.metric("Monthly savings", money(r["monthly_savings"]))
# #     d4.metric("Action", r["action"].upper())
# #     e1, e2, e3 = st.columns(3)
# #     e1.metric("Confidence", f"{r['confidence']:.0f}/100")
# #     e2.metric("Failure risk", f"{r['failure_risk']:.1f}%")
# #     e3.metric("Risk level", r["risk_level"])
# #     st.markdown(f"**Why:** {r['reason']}")
# #     st.caption("Human review required before any change is made.")

# #     g = metrics[metrics["vm_id"] == vm].sort_values("timestamp")
# #     for label, avg_col, max_col, pred, need, cur_cap, rec_cap in (
# #         (
# #             "CPU",
# #             "average_usage_cpus",
# #             "maximum_usage_cpus",
# #             r["predicted_peak_cpu"],
# #             r["required_cpu_with_buffer"],
# #             cur.cpu_fraction,
# #             rec.cpu_fraction,
# #         ),
# #         (
# #             "Memory",
# #             "average_usage_memory",
# #             "maximum_usage_memory",
# #             r["predicted_peak_memory"],
# #             r["required_mem_with_buffer"],
# #             cur.mem_fraction,
# #             rec.mem_fraction,
# #         ),
# #     ):
# #         pct = lambda v: (
# #             100 * v / cur_cap
# #         )  # express everything as % of the CURRENT instance
# #         fig = go.Figure()
# #         fig.add_trace(
# #             go.Scatter(
# #                 x=g["timestamp"],
# #                 y=pct(g[avg_col]),
# #                 name="Average usage",
# #                 line=dict(color="#F59E0B", width=1.5),
# #             )
# #         )
# #         if max_col in g.columns:
# #             fig.add_trace(
# #                 go.Scatter(
# #                     x=g["timestamp"],
# #                     y=pct(g[max_col]),
# #                     name="Observed peak",
# #                     line=dict(color="#9CA3AF", width=1),
# #                 )
# #             )
# #         fig.add_hline(
# #             y=pct(pred),
# #             line=dict(color="#7C3AED", dash="dot"),
# #             annotation_text="Predicted peak",
# #             annotation_position="top left",
# #         )
# #         fig.add_hline(
# #             y=pct(need),
# #             line=dict(color="#2563EB", dash="dash"),
# #             annotation_text=f"Peak + {SAFETY_BUFFER:.0%} buffer",
# #             annotation_position="bottom left",
# #         )
# #         fig.add_hline(
# #             y=pct(rec_cap),
# #             line=dict(color="#16A34A"),
# #             annotation_text=f"Recommended capacity ({rec.name})",
# #             annotation_position="top right",
# #         )
# #         fig.add_hline(
# #             y=100,
# #             line=dict(color="#DC2626"),
# #             annotation_text=f"Current capacity ({cur.name})",
# #             annotation_position="top right",
# #         )
# #         fig.update_layout(
# #             title=f"{label} - % of current instance capacity",
# #             yaxis_title="% of current capacity",
# #             xaxis_title=None,
# #             legend=dict(orientation="h", y=-0.2),
# #             yaxis_range=[0, max(110, pct(g[avg_col]).max() * 1.1)],
# #         )
# #         st.plotly_chart(fig, use_container_width=True)

# #     cmp = pd.DataFrame(
# #         {
# #             "": ["vCPU cores", "Memory (GB)", "Monthly cost"],
# #             f"Current ({cur.name})": [
# #                 str(cur.cores),
# #                 str(cur.mem_gb),
# #                 f"${cur.monthly_cost:,.0f}",
# #             ],
# #             f"Recommended ({rec.name})": [
# #                 str(rec.cores),
# #                 str(rec.mem_gb),
# #                 f"${rec.monthly_cost:,.0f}",
# #             ],
# #         }
# #     )
# #     st.table(cmp.set_index(""))

# # # ── Model ──────────────────────────────────────────────────────────────────────
# # with tab_model:
# #     eng = get_engine()
# #     m = eng.meta
# #     st.markdown(
# #         f"Trained **{m['trained_at']}** on {m['n_train']:,} rows, tested on {m['n_test']:,} "
# #         "later rows (chronological split)."
# #     )
# #     st.success(
# #         "Leakage-free: `maximum_usage_cpus`, `maximum_usage_memory`, `cpu_burst_ratio` and "
# #         "`cpu_range` are never model inputs (runtime assertion enforced).",
# #         icon="",
# #     )
# #     mt = pd.DataFrame(m["metrics"]).T.rename_axis("Model").reset_index()
# #     st.dataframe(mt, hide_index=True, use_container_width=True)
# #     imp = pd.Series(m["feature_importances"]["cpu_peak"]).nlargest(10).sort_values()
# #     st.plotly_chart(
# #         px.bar(
# #             imp,
# #             orientation="h",
# #             title="Top features - peak CPU model",
# #             labels={"value": "Importance", "index": ""},
# #         ).update_layout(showlegend=False),
# #         use_container_width=True,
# #     )

# from __future__ import annotations

# import os
# import sys
# from pathlib import Path

# ROOT = Path(__file__).resolve().parents[1]
# sys.path.insert(0, str(ROOT))

# import pandas as pd
# import plotly.express as px
# import plotly.graph_objects as go
# import streamlit as st
# from model.recommender import (
#     DATA_PATH,
#     SAFETY_BUFFER,
#     TIER_BY_NAME,
#     ArtifactsMissingError,
#     get_engine,
#     load_metrics_csv,
#     summarize,
# )

# st.set_page_config(
#     page_title="Cloud Right-Sizing Advisor", page_icon="~", layout="wide"
# )

# RISK_COLORS = {"LOW": "#16A34A", "MEDIUM": "#D97706", "HIGH": "#DC2626"}
# ACTION_COLORS = {"downsize": "#2563EB", "keep": "#6B7280", "upsize": "#DC2626"}
# # NEW — color map for behavior-profile clusters, used in filters/charts below
# CLUSTER_COLORS = {
#     "idle": "#64748B",
#     "steady": "#2563EB",
#     "bursty": "#D97706",
#     "seasonal/irregular": "#7C3AED",
#     "unknown": "#9CA3AF",
# }


# @st.cache_data(show_spinner="Running the model on 30 days of metrics...")
# def load(path: str, mtime: float):
#     metrics = load_metrics_csv(Path(path))
#     metrics["timestamp"] = pd.to_datetime(metrics["timestamp"], utc=True).dt.tz_convert(
#         None
#     )
#     return metrics, get_engine().recommend(metrics)


# def money(x: float) -> str:
#     return f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}"


# # ── Load ───────────────────────────────────────────────────────────────────────
# st.title("Cloud Right-Sizing Advisor")
# st.info(
#     "**Advisory only.** This tool never resizes anything. Every recommendation requires "
#     "review and approval by your cloud team.",
#     icon="",
# )

# try:
#     metrics, recs = load(str(DATA_PATH), os.path.getmtime(DATA_PATH))
# except FileNotFoundError:
#     st.error("No metrics data found. Run `python scripts/generate_data.py` first.")
#     st.stop()
# except ArtifactsMissingError as e:
#     st.error(f"{e}")
#     st.stop()
# except ValueError as e:
#     st.error(f"Could not process metrics data: {e}")
#     st.stop()

# # NEW — whether cluster-aware columns are present (false until clustering has
# # been run at least once and recommender.py picked up data/vm_clusters.csv)
# has_clusters = "cluster_label" in recs.columns

# # ── Sidebar filters ────────────────────────────────────────────────────────────
# st.sidebar.header("Filters")
# actions = st.sidebar.multiselect(
#     "Action", ["downsize", "keep", "upsize"], default=["downsize", "keep", "upsize"]
# )
# risks = st.sidebar.multiselect(
#     "Risk level", ["LOW", "MEDIUM", "HIGH"], default=["LOW", "MEDIUM", "HIGH"]
# )
# min_conf = st.sidebar.slider("Minimum confidence", 0, 100, 0)

# # NEW — behavior-profile filter, only shown once clustering has actually run
# if has_clusters:
#     cluster_options = sorted(recs["cluster_label"].dropna().unique().tolist())
#     clusters = st.sidebar.multiselect(
#         "Behavior profile", cluster_options, default=cluster_options
#     )
# else:
#     clusters = None
#     st.sidebar.caption(
#         "Behavior-profile clustering not yet run. "
#         "Run `python -m scripts.workload_clustering` to enable per-cluster filters."
#     )

# # NEW — caption now reflects a per-cluster buffer instead of one fixed number
# if has_clusters:
#     avg_buffer = recs["safety_buffer_used"].mean()
#     st.sidebar.caption(
#         f"Safety buffer: **adaptive by behavior profile** (avg {avg_buffer:.0%} across "
#         f"the fleet; ranges from idle VMs at 20% up to seasonal/bursty VMs at 45-50%). "
#         "Maximum usage is never a model input (leakage-free)."
#     )
# else:
#     st.sidebar.caption(
#         f"Safety buffer: **{SAFETY_BUFFER:.0%}** above predicted peak. "
#         "Maximum usage is never a model input (leakage-free)."
#     )

# if st.sidebar.button("Reload data"):
#     st.cache_data.clear()
#     st.rerun()

# view = recs[
#     recs["action"].isin(actions)
#     & recs["risk_level"].isin(risks)
#     & (recs["confidence"] >= min_conf)
# ]
# if has_clusters and clusters is not None:
#     view = view[view["cluster_label"].isin(clusters)]
# s = summarize(recs)

# # ── KPIs ───────────────────────────────────────────────────────────────────────
# c1, c2, c3, c4, c5, c6 = st.columns(6)
# c1.metric("Monthly spend", money(s["current_monthly_spend"]))
# c2.metric(
#     "Net monthly savings",
#     money(s["potential_monthly_savings"]),
#     f"{s['savings_pct_of_spend']}% of spend",
# )
# c3.metric("LOW-risk downsize savings", money(s["low_risk_monthly_savings"]))
# c4.metric("VMs to downsize", s["by_action"].get("downsize", 0), f"of {s['vm_count']}")
# c5.metric("Avg confidence", f"{s['avg_confidence']:.0f}/100")
# # NEW — 6th KPI: shows the buffer is adaptive, falls back to the fixed value otherwise
# if "avg_safety_buffer_used" in s:
#     c6.metric("Avg safety buffer", f"{s['avg_safety_buffer_used']:.0%}")
# else:
#     c6.metric("Safety buffer", f"{SAFETY_BUFFER:.0%}")

# tab_over, tab_detail, tab_model = st.tabs(["Overview", "VM detail", "Model"])

# # ── Overview ───────────────────────────────────────────────────────────────────
# with tab_over:
#     if view.empty:
#         st.warning("No VMs match the current filters.")
#     else:
#         left, right = st.columns(2)
#         cost = view.melt(
#             id_vars="vm_id",
#             value_vars=["current_monthly_cost", "recommended_monthly_cost"],
#             var_name="Plan",
#             value_name="Monthly cost (USD)",
#         )
#         cost["Plan"] = cost["Plan"].map(
#             {
#                 "current_monthly_cost": "Current",
#                 "recommended_monthly_cost": "Recommended",
#             }
#         )
#         fig = px.bar(
#             cost,
#             x="vm_id",
#             y="Monthly cost (USD)",
#             color="Plan",
#             barmode="group",
#             color_discrete_map={"Current": "#9CA3AF", "Recommended": "#2563EB"},
#             title="Current vs recommended monthly cost",
#         )
#         fig.update_layout(xaxis_title=None, legend_title=None)
#         left.plotly_chart(fig, use_container_width=True)

#         util = view.melt(
#             id_vars="vm_id",
#             value_vars=["avg_cpu_util_pct", "predicted_peak_cpu_pct_of_current"],
#             var_name="Metric",
#             value_name="% of current instance",
#         )
#         util["Metric"] = util["Metric"].map(
#             {
#                 "avg_cpu_util_pct": "Average CPU",
#                 "predicted_peak_cpu_pct_of_current": "Predicted peak CPU",
#             }
#         )
#         fig = px.bar(
#             util,
#             x="vm_id",
#             y="% of current instance",
#             color="Metric",
#             barmode="group",
#             color_discrete_map={
#                 "Average CPU": "#F59E0B",
#                 "Predicted peak CPU": "#7C3AED",
#             },
#             title="CPU: average vs predicted peak (bursty VMs stand out)",
#         )
#         fig.update_layout(xaxis_title=None, legend_title=None)
#         right.plotly_chart(fig, use_container_width=True)

#         fig = px.scatter(
#             view,
#             x="confidence",
#             y="failure_risk",
#             color="risk_level",
#             size=view["monthly_savings"].abs() + 10,
#             hover_name="vm_id",
#             color_discrete_map=RISK_COLORS,
#             hover_data={
#                 "action": True,
#                 "recommended_tier": True,
#                 "monthly_savings": ":.0f",
#                 **({"cluster_label": True} if has_clusters else {}),
#             },
#             title="Confidence vs failure risk (bubble size = $ impact)",
#         )
#         fig.update_layout(
#             xaxis_title="Confidence score (0-100)", yaxis_title="Failure risk (%)"
#         )
#         st.plotly_chart(fig, use_container_width=True)

#         # NEW — fleet-level behavior-profile breakdown, mirrors summarize()'s
#         # by_cluster_label output. Shown only once clustering has run.
#         if has_clusters:
#             st.subheader("Fleet behavior profile")
#             cl1, cl2 = st.columns([1, 2])
#             cluster_counts = (
#                 view["cluster_label"]
#                 .value_counts()
#                 .rename_axis("Profile")
#                 .reset_index(name="VMs")
#             )
#             fig_cl = px.pie(
#                 cluster_counts,
#                 names="Profile",
#                 values="VMs",
#                 color="Profile",
#                 color_discrete_map=CLUSTER_COLORS,
#                 title="VMs by behavior profile",
#             )
#             cl1.plotly_chart(fig_cl, use_container_width=True)

#             buffer_by_cluster = (
#                 view.groupby("cluster_label")["safety_buffer_used"]
#                 .mean()
#                 .reset_index()
#                 .rename(
#                     columns={
#                         "cluster_label": "Profile",
#                         "safety_buffer_used": "Avg buffer",
#                     }
#                 )
#             )
#             fig_buf = px.bar(
#                 buffer_by_cluster,
#                 x="Profile",
#                 y="Avg buffer",
#                 color="Profile",
#                 color_discrete_map=CLUSTER_COLORS,
#                 title="Safety buffer applied, by behavior profile",
#             )
#             fig_buf.update_layout(
#                 yaxis_tickformat=".0%", showlegend=False, xaxis_title=None
#             )
#             cl2.plotly_chart(fig_buf, use_container_width=True)

#         st.subheader("Recommendations")
#         table_cols = [
#             "vm_id",
#             "current_tier",
#             "recommended_tier",
#             "action",
#             "monthly_savings",
#             "confidence",
#             "failure_risk",
#             "risk_level",
#             "reason",
#         ]
#         rename_map = {
#             "vm_id": "VM",
#             "current_tier": "Current",
#             "recommended_tier": "Recommended",
#             "action": "Action",
#             "monthly_savings": "Savings / mo ($)",
#             "confidence": "Confidence",
#             "failure_risk": "Failure risk (%)",
#             "risk_level": "Risk",
#             "reason": "Why",
#         }
#         # NEW — insert Cluster column right after Risk if available
#         if has_clusters:
#             table_cols.insert(table_cols.index("risk_level") + 1, "cluster_label")
#             rename_map["cluster_label"] = "Cluster"

#         table = view[table_cols].rename(columns=rename_map)
#         st.dataframe(
#             table,
#             hide_index=True,
#             use_container_width=True,
#             column_config={
#                 "Savings / mo ($)": st.column_config.NumberColumn(format="$%.0f"),
#                 "Confidence": st.column_config.ProgressColumn(
#                     min_value=0, max_value=100, format="%.0f"
#                 ),
#                 "Failure risk (%)": st.column_config.NumberColumn(format="%.1f"),
#             },
#         )
#         st.download_button(
#             "Download recommendations (CSV)",
#             view.to_csv(index=False),
#             "rightsizing_recommendations.csv",
#             "text/csv",
#         )

# # ── VM detail ──────────────────────────────────────────────────────────────────
# with tab_detail:
#     vm = st.selectbox("Select a VM", recs["vm_id"].tolist())
#     r = recs[recs["vm_id"] == vm].iloc[0]
#     cur, rec = TIER_BY_NAME[r["current_tier"]], TIER_BY_NAME[r["recommended_tier"]]

#     # NEW — per-VM buffer, falls back to the fixed constant if clustering hasn't run
#     vm_buffer = r["safety_buffer_used"] if "safety_buffer_used" in r else SAFETY_BUFFER

#     d1, d2, d3, d4 = st.columns(4)
#     d1.metric(
#         "Current tier", f"{cur.name}", f"${cur.monthly_cost:,.0f}/mo", delta_color="off"
#     )
#     d2.metric(
#         "Recommended", f"{rec.name}", f"${rec.monthly_cost:,.0f}/mo", delta_color="off"
#     )
#     d3.metric("Monthly savings", money(r["monthly_savings"]))
#     d4.metric("Action", r["action"].upper())

#     # NEW — extra row of metrics: cluster label + the buffer actually applied
#     if has_clusters:
#         e0, e1, e2, e3 = st.columns(4)
#         e0.metric("Behavior profile", r.get("cluster_label", "unknown").title())
#     else:
#         e1, e2, e3 = st.columns(3)
#     e1.metric("Confidence", f"{r['confidence']:.0f}/100")
#     e2.metric("Failure risk", f"{r['failure_risk']:.1f}%")
#     e3.metric("Risk level", r["risk_level"])
#     st.markdown(f"**Why:** {r['reason']}")
#     st.caption("Human review required before any change is made.")

#     g = metrics[metrics["vm_id"] == vm].sort_values("timestamp")
#     for label, avg_col, max_col, pred, need, cur_cap, rec_cap in (
#         (
#             "CPU",
#             "average_usage_cpus",
#             "maximum_usage_cpus",
#             r["predicted_peak_cpu"],
#             r["required_cpu_with_buffer"],
#             cur.cpu_fraction,
#             rec.cpu_fraction,
#         ),
#         (
#             "Memory",
#             "average_usage_memory",
#             "maximum_usage_memory",
#             r["predicted_peak_memory"],
#             r["required_mem_with_buffer"],
#             cur.mem_fraction,
#             rec.mem_fraction,
#         ),
#     ):
#         pct = lambda v: (
#             100 * v / cur_cap
#         )  # express everything as % of the CURRENT instance
#         fig = go.Figure()
#         fig.add_trace(
#             go.Scatter(
#                 x=g["timestamp"],
#                 y=pct(g[avg_col]),
#                 name="Average usage",
#                 line=dict(color="#F59E0B", width=1.5),
#             )
#         )
#         if max_col in g.columns:
#             fig.add_trace(
#                 go.Scatter(
#                     x=g["timestamp"],
#                     y=pct(g[max_col]),
#                     name="Observed peak",
#                     line=dict(color="#9CA3AF", width=1),
#                 )
#             )
#         fig.add_hline(
#             y=pct(pred),
#             line=dict(color="#7C3AED", dash="dot"),
#             annotation_text="Predicted peak",
#             annotation_position="top left",
#         )
#         fig.add_hline(
#             y=pct(need),
#             line=dict(color="#2563EB", dash="dash"),
#             # NEW — annotation now shows the actual per-VM buffer used
#             annotation_text=f"Peak + {vm_buffer:.0%} buffer",
#             annotation_position="bottom left",
#         )
#         fig.add_hline(
#             y=pct(rec_cap),
#             line=dict(color="#16A34A"),
#             annotation_text=f"Recommended capacity ({rec.name})",
#             annotation_position="top right",
#         )
#         fig.add_hline(
#             y=100,
#             line=dict(color="#DC2626"),
#             annotation_text=f"Current capacity ({cur.name})",
#             annotation_position="top right",
#         )
#         fig.update_layout(
#             title=f"{label} - % of current instance capacity",
#             yaxis_title="% of current capacity",
#             xaxis_title=None,
#             legend=dict(orientation="h", y=-0.2),
#             yaxis_range=[0, max(110, pct(g[avg_col]).max() * 1.1)],
#         )
#         st.plotly_chart(fig, use_container_width=True)

#     cmp = pd.DataFrame(
#         {
#             "": ["vCPU cores", "Memory (GB)", "Monthly cost"],
#             f"Current ({cur.name})": [
#                 str(cur.cores),
#                 str(cur.mem_gb),
#                 f"${cur.monthly_cost:,.0f}",
#             ],
#             f"Recommended ({rec.name})": [
#                 str(rec.cores),
#                 str(rec.mem_gb),
#                 f"${rec.monthly_cost:,.0f}",
#             ],
#         }
#     )
#     st.table(cmp.set_index(""))

# # ── Model ──────────────────────────────────────────────────────────────────────
# with tab_model:
#     eng = get_engine()
#     m = eng.meta
#     st.markdown(
#         f"Trained **{m['trained_at']}** on {m['n_train']:,} rows, tested on {m['n_test']:,} "
#         "later rows (chronological split)."
#     )
#     st.success(
#         "Leakage-free: `maximum_usage_cpus`, `maximum_usage_memory`, `cpu_burst_ratio` and "
#         "`cpu_range` are never model inputs (runtime assertion enforced).",
#         icon="",
#     )
#     mt = pd.DataFrame(m["metrics"]).T.rename_axis("Model").reset_index()
#     st.dataframe(mt, hide_index=True, use_container_width=True)
#     imp = pd.Series(m["feature_importances"]["cpu_peak"]).nlargest(10).sort_values()
#     st.plotly_chart(
#         px.bar(
#             imp,
#             orientation="h",
#             title="Top features - peak CPU model",
#             labels={"value": "Importance", "index": ""},
#         ).update_layout(showlegend=False),
#         use_container_width=True,
#     )

#     # NEW — shows whether cluster-aware behavior profiling is active, and its effect
#     if has_clusters:
#         st.subheader("Behavior-profile clustering")
#         st.success(
#             "Cluster-aware policy active: safety buffer and confidence weighting are "
#             "now adjusted per VM based on its usage-behavior profile "
#             "(idle / steady / bursty / seasonal), instead of one fixed value for all VMs.",
#             icon="",
#         )
#         cluster_summary = (
#             recs.groupby("cluster_label")
#             .agg(
#                 vm_count=("vm_id", "count"),
#                 avg_buffer=("safety_buffer_used", "mean"),
#                 avg_confidence=("confidence", "mean"),
#             )
#             .reset_index()
#             .rename(
#                 columns={
#                     "cluster_label": "Profile",
#                     "vm_count": "VMs",
#                     "avg_buffer": "Avg buffer",
#                     "avg_confidence": "Avg confidence",
#                 }
#             )
#         )
#         cluster_summary["Avg buffer"] = cluster_summary["Avg buffer"].map(
#             lambda x: f"{x:.0%}"
#         )
#         cluster_summary["Avg confidence"] = cluster_summary["Avg confidence"].round(1)
#         st.dataframe(cluster_summary, hide_index=True, use_container_width=True)
#     else:
#         st.info(
#             "Behavior-profile clustering not yet run — all VMs currently use the same "
#             f"fixed {SAFETY_BUFFER:.0%} safety buffer and confidence weighting. "
#             "Run `python -m scripts.workload_clustering` to enable per-VM adaptive buffers.",
#             icon="",
#         )


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
from dotenv import load_dotenv
from model.rag_chat import AdvisorChat  # NEW — "Ask the Advisor" RAG chat engine
from model.recommender import (
    DATA_PATH,
    SAFETY_BUFFER,
    TIER_BY_NAME,
    ArtifactsMissingError,
    get_engine,
    load_metrics_csv,
    summarize,
)

load_dotenv()

st.set_page_config(
    page_title="Cloud Right-Sizing Advisor", page_icon="~", layout="wide"
)

RISK_COLORS = {"LOW": "#16A34A", "MEDIUM": "#D97706", "HIGH": "#DC2626"}
ACTION_COLORS = {"downsize": "#2563EB", "keep": "#6B7280", "upsize": "#DC2626"}
CLUSTER_COLORS = {
    "idle": "#64748B",
    "steady": "#2563EB",
    "bursty": "#D97706",
    "seasonal/irregular": "#7C3AED",
    "unknown": "#9CA3AF",
}


@st.cache_data(show_spinner="Running the model on 30 days of metrics...")
def load(path: str, mtime: float):
    metrics = load_metrics_csv(Path(path))
    metrics["timestamp"] = pd.to_datetime(metrics["timestamp"], utc=True).dt.tz_convert(
        None
    )
    return metrics, get_engine().recommend(metrics)


# NEW — cache the chat engine separately from the data load, since rebuilding
# the TF-IDF index is cheap but no need to redo it on every Streamlit rerun
# unless the underlying recommendations actually changed.
@st.cache_resource(show_spinner="Indexing recommendations for chat...")
def get_chat_engine(_recs: pd.DataFrame, cache_key: str) -> AdvisorChat:
    return AdvisorChat(_recs)


def money(x: float) -> str:
    return f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}"


# ── Load ───────────────────────────────────────────────────────────────────────
st.title("Cloud Right-Sizing Advisor")
st.info(
    "**Advisory only.** This tool never resizes anything. Every recommendation requires "
    "review and approval by your cloud team.",
    icon="",
)

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

has_clusters = "cluster_label" in recs.columns

# ── Sidebar filters ────────────────────────────────────────────────────────────
st.sidebar.header("Filters")
actions = st.sidebar.multiselect(
    "Action", ["downsize", "keep", "upsize"], default=["downsize", "keep", "upsize"]
)
risks = st.sidebar.multiselect(
    "Risk level", ["LOW", "MEDIUM", "HIGH"], default=["LOW", "MEDIUM", "HIGH"]
)
min_conf = st.sidebar.slider("Minimum confidence", 0, 100, 0)

if has_clusters:
    cluster_options = sorted(recs["cluster_label"].dropna().unique().tolist())
    clusters = st.sidebar.multiselect(
        "Behavior profile", cluster_options, default=cluster_options
    )
else:
    clusters = None
    st.sidebar.caption(
        "Behavior-profile clustering not yet run. "
        "Run `python -m scripts.workload_clustering` to enable per-cluster filters."
    )

if has_clusters:
    avg_buffer = recs["safety_buffer_used"].mean()
    st.sidebar.caption(
        f"Safety buffer: **adaptive by behavior profile** (avg {avg_buffer:.0%} across "
        f"the fleet; ranges from idle VMs at 20% up to seasonal/bursty VMs at 45-50%). "
        "Maximum usage is never a model input (leakage-free)."
    )
else:
    st.sidebar.caption(
        f"Safety buffer: **{SAFETY_BUFFER:.0%}** above predicted peak. "
        "Maximum usage is never a model input (leakage-free)."
    )

if st.sidebar.button("Reload data"):
    st.cache_data.clear()
    st.cache_resource.clear()  # NEW — also clear the chat index on reload
    st.rerun()

view = recs[
    recs["action"].isin(actions)
    & recs["risk_level"].isin(risks)
    & (recs["confidence"] >= min_conf)
]
if has_clusters and clusters is not None:
    view = view[view["cluster_label"].isin(clusters)]
s = summarize(recs)

# ── KPIs ───────────────────────────────────────────────────────────────────────
c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Monthly spend", money(s["current_monthly_spend"]))
c2.metric(
    "Net monthly savings",
    money(s["potential_monthly_savings"]),
    f"{s['savings_pct_of_spend']}% of spend",
)
c3.metric("LOW-risk downsize savings", money(s["low_risk_monthly_savings"]))
c4.metric("VMs to downsize", s["by_action"].get("downsize", 0), f"of {s['vm_count']}")
c5.metric("Avg confidence", f"{s['avg_confidence']:.0f}/100")
if "avg_safety_buffer_used" in s:
    c6.metric("Avg safety buffer", f"{s['avg_safety_buffer_used']:.0%}")
else:
    c6.metric("Safety buffer", f"{SAFETY_BUFFER:.0%}")

# NEW — added "Ask the Advisor" as a new tab
tab_over, tab_detail, tab_chat, tab_model = st.tabs(
    ["Overview", "VM detail", "Ask the Advisor", "Model"]
)

# ── Overview ───────────────────────────────────────────────────────────────────
with tab_over:
    if view.empty:
        st.warning("No VMs match the current filters.")
    else:
        left, right = st.columns(2)
        cost = view.melt(
            id_vars="vm_id",
            value_vars=["current_monthly_cost", "recommended_monthly_cost"],
            var_name="Plan",
            value_name="Monthly cost (USD)",
        )
        cost["Plan"] = cost["Plan"].map(
            {
                "current_monthly_cost": "Current",
                "recommended_monthly_cost": "Recommended",
            }
        )
        fig = px.bar(
            cost,
            x="vm_id",
            y="Monthly cost (USD)",
            color="Plan",
            barmode="group",
            color_discrete_map={"Current": "#9CA3AF", "Recommended": "#2563EB"},
            title="Current vs recommended monthly cost",
        )
        fig.update_layout(xaxis_title=None, legend_title=None)
        left.plotly_chart(fig, use_container_width=True)

        util = view.melt(
            id_vars="vm_id",
            value_vars=["avg_cpu_util_pct", "predicted_peak_cpu_pct_of_current"],
            var_name="Metric",
            value_name="% of current instance",
        )
        util["Metric"] = util["Metric"].map(
            {
                "avg_cpu_util_pct": "Average CPU",
                "predicted_peak_cpu_pct_of_current": "Predicted peak CPU",
            }
        )
        fig = px.bar(
            util,
            x="vm_id",
            y="% of current instance",
            color="Metric",
            barmode="group",
            color_discrete_map={
                "Average CPU": "#F59E0B",
                "Predicted peak CPU": "#7C3AED",
            },
            title="CPU: average vs predicted peak (bursty VMs stand out)",
        )
        fig.update_layout(xaxis_title=None, legend_title=None)
        right.plotly_chart(fig, use_container_width=True)

        fig = px.scatter(
            view,
            x="confidence",
            y="failure_risk",
            color="risk_level",
            size=view["monthly_savings"].abs() + 10,
            hover_name="vm_id",
            color_discrete_map=RISK_COLORS,
            hover_data={
                "action": True,
                "recommended_tier": True,
                "monthly_savings": ":.0f",
                **({"cluster_label": True} if has_clusters else {}),
            },
            title="Confidence vs failure risk (bubble size = $ impact)",
        )
        fig.update_layout(
            xaxis_title="Confidence score (0-100)", yaxis_title="Failure risk (%)"
        )
        st.plotly_chart(fig, use_container_width=True)

        if has_clusters:
            st.subheader("Fleet behavior profile")
            cl1, cl2 = st.columns([1, 2])
            cluster_counts = (
                view["cluster_label"]
                .value_counts()
                .rename_axis("Profile")
                .reset_index(name="VMs")
            )
            fig_cl = px.pie(
                cluster_counts,
                names="Profile",
                values="VMs",
                color="Profile",
                color_discrete_map=CLUSTER_COLORS,
                title="VMs by behavior profile",
            )
            cl1.plotly_chart(fig_cl, use_container_width=True)

            buffer_by_cluster = (
                view.groupby("cluster_label")["safety_buffer_used"]
                .mean()
                .reset_index()
                .rename(
                    columns={
                        "cluster_label": "Profile",
                        "safety_buffer_used": "Avg buffer",
                    }
                )
            )
            fig_buf = px.bar(
                buffer_by_cluster,
                x="Profile",
                y="Avg buffer",
                color="Profile",
                color_discrete_map=CLUSTER_COLORS,
                title="Safety buffer applied, by behavior profile",
            )
            fig_buf.update_layout(
                yaxis_tickformat=".0%", showlegend=False, xaxis_title=None
            )
            cl2.plotly_chart(fig_buf, use_container_width=True)

        st.subheader("Recommendations")
        table_cols = [
            "vm_id",
            "current_tier",
            "recommended_tier",
            "action",
            "monthly_savings",
            "confidence",
            "failure_risk",
            "risk_level",
            "reason",
        ]
        rename_map = {
            "vm_id": "VM",
            "current_tier": "Current",
            "recommended_tier": "Recommended",
            "action": "Action",
            "monthly_savings": "Savings / mo ($)",
            "confidence": "Confidence",
            "failure_risk": "Failure risk (%)",
            "risk_level": "Risk",
            "reason": "Why",
        }
        if has_clusters:
            table_cols.insert(table_cols.index("risk_level") + 1, "cluster_label")
            rename_map["cluster_label"] = "Cluster"

        table = view[table_cols].rename(columns=rename_map)
        st.dataframe(
            table,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Savings / mo ($)": st.column_config.NumberColumn(format="$%.0f"),
                "Confidence": st.column_config.ProgressColumn(
                    min_value=0, max_value=100, format="%.0f"
                ),
                "Failure risk (%)": st.column_config.NumberColumn(format="%.1f"),
            },
        )
        st.download_button(
            "Download recommendations (CSV)",
            view.to_csv(index=False),
            "rightsizing_recommendations.csv",
            "text/csv",
        )

# ── VM detail ──────────────────────────────────────────────────────────────────
with tab_detail:
    vm = st.selectbox("Select a VM", recs["vm_id"].tolist())
    r = recs[recs["vm_id"] == vm].iloc[0]
    cur, rec = TIER_BY_NAME[r["current_tier"]], TIER_BY_NAME[r["recommended_tier"]]

    vm_buffer = r["safety_buffer_used"] if "safety_buffer_used" in r else SAFETY_BUFFER

    d1, d2, d3, d4 = st.columns(4)
    d1.metric(
        "Current tier", f"{cur.name}", f"${cur.monthly_cost:,.0f}/mo", delta_color="off"
    )
    d2.metric(
        "Recommended", f"{rec.name}", f"${rec.monthly_cost:,.0f}/mo", delta_color="off"
    )
    d3.metric("Monthly savings", money(r["monthly_savings"]))
    d4.metric("Action", r["action"].upper())

    if has_clusters:
        e0, e1, e2, e3 = st.columns(4)
        e0.metric("Behavior profile", r.get("cluster_label", "unknown").title())
    else:
        e1, e2, e3 = st.columns(3)
    e1.metric("Confidence", f"{r['confidence']:.0f}/100")
    e2.metric("Failure risk", f"{r['failure_risk']:.1f}%")
    e3.metric("Risk level", r["risk_level"])
    st.markdown(f"**Why:** {r['reason']}")
    st.caption("Human review required before any change is made.")

    g = metrics[metrics["vm_id"] == vm].sort_values("timestamp")
    for label, avg_col, max_col, pred, need, cur_cap, rec_cap in (
        (
            "CPU",
            "average_usage_cpus",
            "maximum_usage_cpus",
            r["predicted_peak_cpu"],
            r["required_cpu_with_buffer"],
            cur.cpu_fraction,
            rec.cpu_fraction,
        ),
        (
            "Memory",
            "average_usage_memory",
            "maximum_usage_memory",
            r["predicted_peak_memory"],
            r["required_mem_with_buffer"],
            cur.mem_fraction,
            rec.mem_fraction,
        ),
    ):
        pct = lambda v: (
            100 * v / cur_cap
        )  # express everything as % of the CURRENT instance
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=g["timestamp"],
                y=pct(g[avg_col]),
                name="Average usage",
                line=dict(color="#F59E0B", width=1.5),
            )
        )
        if max_col in g.columns:
            fig.add_trace(
                go.Scatter(
                    x=g["timestamp"],
                    y=pct(g[max_col]),
                    name="Observed peak",
                    line=dict(color="#9CA3AF", width=1),
                )
            )
        fig.add_hline(
            y=pct(pred),
            line=dict(color="#7C3AED", dash="dot"),
            annotation_text="Predicted peak",
            annotation_position="top left",
        )
        fig.add_hline(
            y=pct(need),
            line=dict(color="#2563EB", dash="dash"),
            annotation_text=f"Peak + {vm_buffer:.0%} buffer",
            annotation_position="bottom left",
        )
        fig.add_hline(
            y=pct(rec_cap),
            line=dict(color="#16A34A"),
            annotation_text=f"Recommended capacity ({rec.name})",
            annotation_position="top right",
        )
        fig.add_hline(
            y=100,
            line=dict(color="#DC2626"),
            annotation_text=f"Current capacity ({cur.name})",
            annotation_position="top right",
        )
        fig.update_layout(
            title=f"{label} - % of current instance capacity",
            yaxis_title="% of current capacity",
            xaxis_title=None,
            legend=dict(orientation="h", y=-0.2),
            yaxis_range=[0, max(110, pct(g[avg_col]).max() * 1.1)],
        )
        st.plotly_chart(fig, use_container_width=True)

    cmp = pd.DataFrame(
        {
            "": ["vCPU cores", "Memory (GB)", "Monthly cost"],
            f"Current ({cur.name})": [
                str(cur.cores),
                str(cur.mem_gb),
                f"${cur.monthly_cost:,.0f}",
            ],
            f"Recommended ({rec.name})": [
                str(rec.cores),
                str(rec.mem_gb),
                f"${rec.monthly_cost:,.0f}",
            ],
        }
    )
    st.table(cmp.set_index(""))

# ── Ask the Advisor (NEW — RAG chat tab) ────────────────────────────────────────
with tab_chat:
    st.subheader("Ask the Advisor")
    st.caption("Ask free-form questions about your fleet.")

    # Build/cache the retrieval index. cache_key tied to row count + a hash of
    # vm_ids so the index rebuilds if the underlying recommendations change,
    # but not on every unrelated Streamlit rerun (e.g. a filter slider move).
    cache_key = f"{len(recs)}-{hash(tuple(recs['vm_id']))}"
    chat_engine = get_chat_engine(recs, cache_key)

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    example_cols = st.columns(4)
    examples = [
        "Which VMs are safe to downsize?",
        "Show me high risk VMs",
        "Which bursty VMs cost the most?",
        "What idle VMs can we shrink?",
    ]
    clicked_example = None
    for col, ex in zip(example_cols, examples):
        if col.button(ex, use_container_width=True):
            clicked_example = ex

    user_question = st.chat_input(
        "Ask about VMs, risk, savings, or behavior profiles..."
    )
    question = clicked_example or user_question

    if question:
        answer, hits = chat_engine.ask(question)
        st.session_state.chat_history.append((question, answer))

    for q, a in reversed(st.session_state.chat_history):
        with st.chat_message("user"):
            st.markdown(q)
        with st.chat_message("assistant"):
            st.markdown(a)

    if not st.session_state.chat_history:
        st.info(icon="", body="Ask a question to get started!")

    if (
        os.environ.get("GROQ_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("AZURE_OPENAI_API_KEY")
    ):
        st.caption("")
    else:
        st.caption("Running in template mode (no LLM API key configured)")

# ── Model ──────────────────────────────────────────────────────────────────────
with tab_model:
    eng = get_engine()
    m = eng.meta
    st.markdown(
        f"Trained **{m['trained_at']}** on {m['n_train']:,} rows, tested on {m['n_test']:,} "
        "later rows (chronological split)."
    )
    st.success(
        "Leakage-free: `maximum_usage_cpus`, `maximum_usage_memory`, `cpu_burst_ratio` and "
        "`cpu_range` are never model inputs (runtime assertion enforced).",
        icon="",
    )
    mt = pd.DataFrame(m["metrics"]).T.rename_axis("Model").reset_index()
    st.dataframe(mt, hide_index=True, use_container_width=True)
    imp = pd.Series(m["feature_importances"]["cpu_peak"]).nlargest(10).sort_values()
    st.plotly_chart(
        px.bar(
            imp,
            orientation="h",
            title="Top features - peak CPU model",
            labels={"value": "Importance", "index": ""},
        ).update_layout(showlegend=False),
        use_container_width=True,
    )

    if has_clusters:
        st.subheader("Behavior-profile clustering")
        st.success(
            "Cluster-aware policy active: safety buffer and confidence weighting are "
            "now adjusted per VM based on its usage-behavior profile "
            "(idle / steady / bursty / seasonal), instead of one fixed value for all VMs.",
            icon="",
        )
        cluster_summary = (
            recs.groupby("cluster_label")
            .agg(
                vm_count=("vm_id", "count"),
                avg_buffer=("safety_buffer_used", "mean"),
                avg_confidence=("confidence", "mean"),
            )
            .reset_index()
            .rename(
                columns={
                    "cluster_label": "Profile",
                    "vm_count": "VMs",
                    "avg_buffer": "Avg buffer",
                    "avg_confidence": "Avg confidence",
                }
            )
        )
        cluster_summary["Avg buffer"] = cluster_summary["Avg buffer"].map(
            lambda x: f"{x:.0%}"
        )
        cluster_summary["Avg confidence"] = cluster_summary["Avg confidence"].round(1)
        st.dataframe(cluster_summary, hide_index=True, use_container_width=True)
    else:
        st.info(
            "Behavior-profile clustering not yet run — all VMs currently use the same "
            f"fixed {SAFETY_BUFFER:.0%} safety buffer and confidence weighting. "
            "Run `python -m scripts.workload_clustering` to enable per-VM adaptive buffers.",
            icon="",
        )
