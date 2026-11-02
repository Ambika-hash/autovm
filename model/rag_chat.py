# # """
# # autovm/model/rag_chat.py

# # "Ask the Advisor" chat engine: takes a free-form question, understands
# # simple intent (filters), retrieves relevant VMs via rag_retriever.py, and
# # synthesizes a grounded natural-language answer.

# # Two answer modes
# # -----------------
# # 1. Template mode (default, no API key needed): builds the answer directly
# #    from the retrieved rows using string templates. Always available,
# #    always grounded -- every number in the answer comes directly from your
# #    recommendations.csv, never invented.
# # 2. LLM mode (optional): if an OpenAI-compatible API key is configured via
# #    environment variables, the retrieved rows are passed to an LLM as
# #    context and it writes a more natural-sounding summary. If the call
# #    fails or no key is set, this silently falls back to template mode --
# #    the chat feature never breaks because of a missing API key.

# # This keeps the "RAG" pattern intact (retrieve real data -> ground the
# # answer in it) regardless of whether an LLM is wired up.
# # """

# # from __future__ import annotations

# # import os
# # import re

# # from model.rag_retriever import RecommendationRetriever, RetrievedVM

# # # Intent keywords -> structured filter values. Checked against the
# # # lower-cased question text.
# # ACTION_KEYWORDS = {
# #     "downsize": ["downsize", "shrink", "smaller", "reduce"],
# #     "upsize": ["upsize", "upgrade", "bigger", "larger", "increase"],
# #     "keep": ["keep", "unchanged", "fine as", "already right"],
# # }
# # RISK_KEYWORDS = {
# #     "HIGH": ["high risk", "risky", "dangerous", "unsafe"],
# #     "MEDIUM": ["medium risk", "moderate risk"],
# #     "LOW": ["low risk", "safe", "safely"],
# # }
# # CLUSTER_KEYWORDS = {
# #     "idle": ["idle", "unused", "doing nothing"],
# #     "bursty": ["bursty", "spiky", "spikes", "burst"],
# #     "steady": ["steady", "stable", "consistent"],
# #     "seasonal/irregular": ["seasonal", "irregular", "periodic", "month-end"],
# # }


# # # def _detect_filters(question: str) -> dict:
# # #     q = question.lower()
# # #     filters = {
# # #         "action": None,
# # #         "risk_level": None,
# # #         "cluster_label": None,
# # #         "min_confidence": None,
# # #     }

# # #     for action, kws in ACTION_KEYWORDS.items():
# # #         if any(kw in q for kw in kws):
# # #             filters["action"] = action
# # #             break

# # #     for risk, kws in RISK_KEYWORDS.items():
# # #         if any(kw in q for kw in kws):
# # #             filters["risk_level"] = risk
# # #             break

# # #     for cluster, kws in CLUSTER_KEYWORDS.items():
# # #         if any(kw in q for kw in kws):
# # #             filters["cluster_label"] = cluster
# # #             break

# # #     # crude "confidence above/over X" detector, e.g. "confidence over 80"
# # #     m = re.search(r"confidence\D{0,10}(\d{1,3})", q)
# # #     if m:
# # #         filters["min_confidence"] = float(m.group(1))


# # #     return filters
# # def _detect_filters(question: str) -> dict:
# #     q = question.lower()
# #     filters = {
# #         "action": None,
# #         "actions": [],  # NEW -- holds multiple actions if more than one is mentioned
# #         "risk_level": None,
# #         "cluster_label": None,
# #         "min_confidence": None,
# #     }

# #     matched_actions = []
# #     for action, kws in ACTION_KEYWORDS.items():
# #         if any(kw in q for kw in kws):
# #             matched_actions.append(action)  # CHANGED -- no break, collect all matches

# #     if len(matched_actions) == 1:
# #         filters["action"] = matched_actions[0]
# #     elif len(matched_actions) > 1:
# #         filters["actions"] = matched_actions  # NEW -- multiple actions detected

# #     for risk, kws in RISK_KEYWORDS.items():  # RESTORED -- was accidentally dropped
# #         if any(kw in q for kw in kws):
# #             filters["risk_level"] = risk
# #             break

# #     for (
# #         cluster,
# #         kws,
# #     ) in CLUSTER_KEYWORDS.items():  # RESTORED -- was accidentally dropped
# #         if any(kw in q for kw in kws):
# #             filters["cluster_label"] = cluster
# #             break

# #     # crude "confidence above/over X" detector, e.g. "confidence over 80"
# #     m = re.search(
# #         r"confidence\D{0,10}(\d{1,3})", q
# #     )  # RESTORED -- was accidentally dropped
# #     if m:
# #         filters["min_confidence"] = float(m.group(1))

# #     return filters  # RESTORED -- this was missing entirely, critical fix


# # def _format_money(x: float) -> str:
# #     return f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}"


# # def _template_answer(question: str, hits: list[RetrievedVM], filters: dict) -> str:
# #     """Builds a grounded natural-language answer directly from retrieved rows."""
# #     if not hits:
# #         return (
# #             "I couldn't find any VMs matching that question in the current "
# #             "recommendations. Try rephrasing, or check the Overview tab filters."
# #         )

# #     lines = []
# #     filt_desc = []
# #     if filters.get("action"):
# #         filt_desc.append(f"action = {filters['action']}")
# #     if filters.get("risk_level"):
# #         filt_desc.append(f"risk = {filters['risk_level']}")
# #     if filters.get("cluster_label"):
# #         filt_desc.append(f"behavior profile = {filters['cluster_label']}")
# #     if filters.get("min_confidence"):
# #         filt_desc.append(f"confidence >= {filters['min_confidence']:.0f}")

# #     header = f"Found {len(hits)} matching VM(s)"
# #     if filt_desc:
# #         header += f" ({', '.join(filt_desc)})"
# #     lines.append(header + ":")
# #     lines.append("")

# #     total_savings = 0.0
# #     for h in hits:
# #         r = h.row
# #         savings = r.get("monthly_savings")
# #         if savings is not None:
# #             total_savings += savings
# #         bits = [f"**{r['vm_id']}**"]
# #         if "action" in r:
# #             bits.append(f"action: {r['action']}")
# #         if "current_tier" in r and "recommended_tier" in r:
# #             bits.append(f"{r['current_tier']} -> {r['recommended_tier']}")
# #         if "risk_level" in r:
# #             bits.append(f"risk: {r['risk_level']}")
# #         if "cluster_label" in r and r.get("cluster_label"):
# #             bits.append(f"profile: {r['cluster_label']}")
# #         if "confidence" in r:
# #             bits.append(f"confidence: {r['confidence']:.0f}/100")
# #         if savings is not None:
# #             bits.append(f"savings: {_format_money(savings)}/mo")
# #         lines.append("- " + " | ".join(str(b) for b in bits))

# #     if len(hits) > 1 and any(h.row.get("monthly_savings") is not None for h in hits):
# #         lines.append("")
# #         lines.append(
# #             f"**Combined monthly impact of these VMs: {_format_money(total_savings)}**"
# #         )

# #     return "\n".join(lines)


# # def _try_llm_answer(question: str, hits: list[RetrievedVM]) -> str | None:
# #     """
# #     Optional LLM synthesis step. Returns None (triggering template fallback)
# #     if no API key is configured or the call fails for any reason -- this
# #     function must NEVER raise, since the chat feature has to keep working
# #     without an LLM wired up.
# #     """
# #     api_key = (
# #         os.environ.get("GROQ_API_KEY")
# #         or os.environ.get("OPENAI_API_KEY")
# #         or os.environ.get("AZURE_OPENAI_API_KEY")
# #     )
# #     if not api_key:
# #         return None

# #     # NEW -- Groq needs a different base_url; OpenAI uses the default (None)
# #     base_url = (
# #         "https://api.groq.com/openai/v1" if os.environ.get("GROQ_API_KEY") else None
# #     )

# #     try:
# #         import openai  # optional dependency -- only imported if a key exists

# #         context_lines = []
# #         for h in hits:
# #             r = h.row
# #             context_lines.append(
# #                 f"- {r.get('vm_id')}: action={r.get('action')}, "
# #                 f"tier {r.get('current_tier')}->{r.get('recommended_tier')}, "
# #                 f"risk={r.get('risk_level')}, profile={r.get('cluster_label')}, "
# #                 f"confidence={r.get('confidence')}, "
# #                 f"savings=${r.get('monthly_savings', 0):.0f}/mo, "
# #                 f"reason: {r.get('reason', '')}"
# #             )
# #         context = "\n".join(context_lines)

# #         prompt = (
# #             "You are a cloud cost advisor. Answer the user's question using ONLY "
# #             "the VM data below. Do not invent numbers or VMs not listed. Be concise.\n\n"
# #             f"VM data:\n{context}\n\nQuestion: {question}\nAnswer:"
# #         )

# #         client = openai.OpenAI(
# #             api_key=api_key, base_url=base_url
# #         )  # NEW -- base_url added
# #         resp = client.chat.completions.create(
# #             model=os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b"),
# #             messages=[{"role": "user", "content": prompt}],
# #             temperature=0.2,
# #             max_tokens=400,
# #         )
# #         return resp.choices[0].message.content.strip()
# #     except Exception as e:
# #         print(f"[LLM DEBUG] LLM call failed: {type(e).__name__} - {e}")  # TEMPORARY
# #         return None  # any failure -> silently fall back to template mode


# # def _detect_vm_id(question: str, known_vm_ids: list[str]) -> str | None:
# #     """Returns the exact vm_id if mentioned verbatim in the question, else None."""
# #     q = question.lower()
# #     for vm_id in known_vm_ids:
# #         if vm_id.lower() in q:
# #             return vm_id
# #     return None


# # class AdvisorChat:
# #     """
# #     Main entry point for the "Ask the Advisor" feature.

# #     Usage:
# #         chat = AdvisorChat(recs_df)
# #         answer, hits = chat.ask("which bursty VMs are high risk?")
# #     """

# #     def __init__(self, recs):
# #         self.recs = recs  # NEW -- keep a reference
# #         self.known_vm_ids = recs["vm_id"].tolist()  # NEW -- for exact-match lookup
# #         self.retriever = RecommendationRetriever(recs)

# #     def ask(self, question: str, k: int = 8) -> tuple[str, list[RetrievedVM]]:
# #         vm_id = _detect_vm_id(question, self.known_vm_ids)
# #         if vm_id:
# #             row = self.recs[self.recs["vm_id"] == vm_id].iloc[0]
# #             hits = [RetrievedVM(vm_id=vm_id, score=1.0, row=row.to_dict())]
# #             llm_answer = _try_llm_answer(question, hits)
# #             answer = llm_answer if llm_answer else _template_answer(question, hits, {})
# #             return answer, hits

# #         filters = _detect_filters(question)

# #         if filters[
# #             "actions"
# #         ]:  # NEW -- question mentioned multiple actions (e.g. "downsize and upsize")
# #             hits = []
# #             for action in filters["actions"]:
# #                 hits.extend(
# #                     self.retriever.filter_then_retrieve(
# #                         question,
# #                         k=k,
# #                         action=action,
# #                         risk_level=filters["risk_level"],
# #                         cluster_label=filters["cluster_label"],
# #                         min_confidence=filters["min_confidence"],
# #                     )
# #                 )
# #         else:
# #             hits = self.retriever.filter_then_retrieve(
# #                 question,
# #                 k=k,
# #                 action=filters["action"],
# #                 risk_level=filters["risk_level"],
# #                 cluster_label=filters["cluster_label"],
# #                 min_confidence=filters["min_confidence"],
# #             )

# #         if not hits:
# #             hits = self.retriever.retrieve(question, k=k)

# #         llm_answer = _try_llm_answer(question, hits) if hits else None
# #         answer = llm_answer if llm_answer else _template_answer(question, hits, filters)
# #         return answer, hits


# # ----------------------------------------


# """
# autovm/model/rag_chat.py

# "Ask the Advisor" chat engine: takes a free-form question, understands
# intent (filters), retrieves relevant VMs via rag_retriever.py, and
# synthesizes a grounded natural-language answer.

# Intent detection -- two modes
# ------------------------------
# 1. LLM-based intent detection (NEW, preferred when an API key is available):
#    the LLM reads the question and outputs structured filters as JSON
#    (action/actions, risk_level, cluster_label, min_confidence). This
#    understands synonyms, grammar variants, and phrasing the old keyword
#    lists could never anticipate (e.g. "upsizing" == "upsize", "right-size"
#    == either, "too big" == "downsize").
# 2. Keyword-based fallback (original, always available, no API key needed):
#    simple substring matching against hardcoded keyword lists. Used
#    automatically if no LLM key is set, or if the LLM intent call fails for
#    any reason -- the chat feature must never break because of a missing
#    or failing LLM.

# Two answer modes (unchanged from before)
# -----------------------------------------
# 1. Template mode (default, no API key needed): builds the answer directly
#    from the retrieved rows using string templates. Always available,
#    always grounded -- every number in the answer comes directly from your
#    recommendations.csv, never invented.
# 2. LLM mode (optional): if an OpenAI-compatible API key is configured via
#    environment variables, the retrieved rows are passed to an LLM as
#    context and it writes a more natural-sounding summary. If the call
#    fails or no key is set, this silently falls back to template mode --
#    the chat feature never breaks because of a missing API key.

# This keeps the "RAG" pattern intact (retrieve real data -> ground the
# answer in it) regardless of whether an LLM is wired up.
# """

# from __future__ import annotations

# import json
# import os
# import re

# from model.rag_retriever import RecommendationRetriever, RetrievedVM

# # Intent keywords -> structured filter values. Used ONLY as a fallback when
# # no LLM is available, or the LLM intent call fails. Checked against the
# # lower-cased question text.
# ACTION_KEYWORDS = {
#     "downsize": [
#         "downsize",
#         "downsizing",
#         "downsized",
#         "shrink",
#         "shrinking",
#         "smaller",
#         "reduce",
#         "reducing",
#     ],
#     "upsize": [
#         "upsize",
#         "upsizing",
#         "upsized",
#         "upgrade",
#         "upgrading",
#         "bigger",
#         "larger",
#         "increase",
#         "increasing",
#     ],
#     "keep": ["keep", "unchanged", "fine as", "already right"],
# }
# RISK_KEYWORDS = {
#     "HIGH": ["high risk", "risky", "dangerous", "unsafe"],
#     "MEDIUM": ["medium risk", "moderate risk"],
#     "LOW": ["low risk", "safe", "safely"],
# }
# CLUSTER_KEYWORDS = {
#     "idle": ["idle", "unused", "doing nothing"],
#     "bursty": ["bursty", "spiky", "spikes", "burst"],
#     "steady": ["steady", "stable", "consistent"],
#     "seasonal/irregular": ["seasonal", "irregular", "periodic", "month-end"],
# }

# VALID_ACTIONS = {"downsize", "upsize", "keep"}
# VALID_RISK_LEVELS = {"HIGH", "MEDIUM", "LOW"}
# VALID_CLUSTERS = {"idle", "steady", "bursty", "seasonal/irregular"}


# def _empty_filters() -> dict:
#     return {
#         "action": None,
#         "actions": [],
#         "risk_level": None,
#         "cluster_label": None,
#         "min_confidence": None,
#     }


# def _detect_filters_keywords(question: str) -> dict:
#     """Original keyword-based fallback -- always available, no API key needed."""
#     q = question.lower()
#     filters = _empty_filters()

#     matched_actions = []
#     for action, kws in ACTION_KEYWORDS.items():
#         if any(kw in q for kw in kws):
#             matched_actions.append(action)

#     if len(matched_actions) == 1:
#         filters["action"] = matched_actions[0]
#     elif len(matched_actions) > 1:
#         filters["actions"] = matched_actions

#     for risk, kws in RISK_KEYWORDS.items():
#         if any(kw in q for kw in kws):
#             filters["risk_level"] = risk
#             break

#     for cluster, kws in CLUSTER_KEYWORDS.items():
#         if any(kw in q for kw in kws):
#             filters["cluster_label"] = cluster
#             break

#     m = re.search(r"confidence\D{0,10}(\d{1,3})", q)
#     if m:
#         filters["min_confidence"] = float(m.group(1))

#     return filters


# def _get_llm_client():
#     """
#     Returns (client, model, base_url) if an LLM is configured, else None.
#     Shared by both intent detection and answer generation so there's only
#     one place that knows how to construct the client.
#     """
#     api_key = (
#         os.environ.get("GROQ_API_KEY")
#         or os.environ.get("OPENAI_API_KEY")
#         or os.environ.get("AZURE_OPENAI_API_KEY")
#     )
#     if not api_key:
#         return None

#     base_url = (
#         "https://api.groq.com/openai/v1" if os.environ.get("GROQ_API_KEY") else None
#     )
#     default_model = (
#         "openai/gpt-oss-20b" if os.environ.get("GROQ_API_KEY") else "gpt-4o-mini"
#     )
#     model = os.environ.get("GROQ_MODEL", default_model)

#     try:
#         import openai

#         client = openai.OpenAI(api_key=api_key, base_url=base_url)
#         return client, model
#     except Exception:
#         return None


# def _detect_filters_llm(question: str) -> dict | None:
#     """
#     NEW -- asks the LLM to interpret the question's intent and return
#     structured filters as JSON. This understands synonyms and phrasing
#     variants ("upsizing"/"upsize", "right-size", "too big", etc.) that a
#     fixed keyword list can never fully anticipate.

#     Returns None (triggering keyword fallback) if no LLM is available or
#     the call/parsing fails for any reason -- this function must NEVER raise.
#     """
#     client_info = _get_llm_client()
#     if not client_info:
#         return None
#     client, model = client_info

#     prompt = (
#         "Extract structured filters from the user's question about VM "
#         "right-sizing recommendations. Respond with ONLY a JSON object, "
#         "no other text, in this exact shape:\n"
#         '{"actions": [...], "risk_level": "HIGH"|"MEDIUM"|"LOW"|null, '
#         '"cluster_label": "idle"|"steady"|"bursty"|"seasonal/irregular"|null, '
#         '"min_confidence": number|null}\n\n'
#         "Rules:\n"
#         '- "actions" is a list; include "downsize" if the question asks about '
#         "downsizing/shrinking/reducing VMs (in any grammatical form, e.g. "
#         '"downsizing", "right-sizing down", "too big"), include "upsize" if '
#         'it asks about upsizing/upgrading/enlarging VMs, include "keep" if '
#         "it asks about VMs that should stay unchanged. Include multiple "
#         "values if the question asks about more than one (e.g. both "
#         "downsize and upsize). Leave the list empty if no action is implied.\n"
#         "- Only set risk_level/cluster_label/min_confidence if the question "
#         "clearly implies them; otherwise use null.\n\n"
#         f"Question: {question}\n"
#         "JSON:"
#     )

#     try:
#         resp = client.chat.completions.create(
#             model=model,
#             messages=[{"role": "user", "content": prompt}],
#             temperature=0.0,  # deterministic -- this is a parsing task, not creative writing
#             max_tokens=200,
#         )
#         raw = resp.choices[0].message.content.strip()

#         # Models sometimes wrap JSON in markdown code fences -- strip those if present
#         raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())

#         parsed = json.loads(raw)

#         filters = _empty_filters()

#         actions = [a for a in parsed.get("actions", []) if a in VALID_ACTIONS]
#         if len(actions) == 1:
#             filters["action"] = actions[0]
#         elif len(actions) > 1:
#             filters["actions"] = actions

#         risk = parsed.get("risk_level")
#         if risk in VALID_RISK_LEVELS:
#             filters["risk_level"] = risk

#         cluster = parsed.get("cluster_label")
#         if cluster in VALID_CLUSTERS:
#             filters["cluster_label"] = cluster

#         conf = parsed.get("min_confidence")
#         if isinstance(conf, (int, float)):
#             filters["min_confidence"] = float(conf)

#         return filters
#     except Exception as e:
#         print(
#             f"[LLM INTENT DEBUG] LLM intent detection failed: {type(e).__name__} - {e}"
#         )  # TEMPORARY
#         return None  # any failure -> caller falls back to keyword detection


# def _detect_filters(question: str) -> dict:
#     """
#     Main entry point for intent detection. Tries the LLM first (understands
#     synonyms/phrasing), falls back to keyword matching if the LLM is
#     unavailable or fails. Never returns None.
#     """
#     llm_filters = _detect_filters_llm(question)
#     if llm_filters is not None:
#         return llm_filters
#     return _detect_filters_keywords(question)


# def _format_money(x: float) -> str:
#     return f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}"


# def _template_answer(question: str, hits: list[RetrievedVM], filters: dict) -> str:
#     """Builds a grounded natural-language answer directly from retrieved rows."""
#     if not hits:
#         return (
#             "I couldn't find any VMs matching that question in the current "
#             "recommendations. Try rephrasing, or check the Overview tab filters."
#         )

#     lines = []
#     filt_desc = []
#     if filters.get("action"):
#         filt_desc.append(f"action = {filters['action']}")
#     if filters.get("actions"):
#         filt_desc.append(f"actions = {', '.join(filters['actions'])}")
#     if filters.get("risk_level"):
#         filt_desc.append(f"risk = {filters['risk_level']}")
#     if filters.get("cluster_label"):
#         filt_desc.append(f"behavior profile = {filters['cluster_label']}")
#     if filters.get("min_confidence"):
#         filt_desc.append(f"confidence >= {filters['min_confidence']:.0f}")

#     header = f"Found {len(hits)} matching VM(s)"
#     if filt_desc:
#         header += f" ({', '.join(filt_desc)})"
#     lines.append(header + ":")
#     lines.append("")

#     total_savings = 0.0
#     for h in hits:
#         r = h.row
#         savings = r.get("monthly_savings")
#         if savings is not None:
#             total_savings += savings
#         bits = [f"**{r['vm_id']}**"]
#         if "action" in r:
#             bits.append(f"action: {r['action']}")
#         if "current_tier" in r and "recommended_tier" in r:
#             bits.append(f"{r['current_tier']} -> {r['recommended_tier']}")
#         if "risk_level" in r:
#             bits.append(f"risk: {r['risk_level']}")
#         if "cluster_label" in r and r.get("cluster_label"):
#             bits.append(f"profile: {r['cluster_label']}")
#         if "confidence" in r:
#             bits.append(f"confidence: {r['confidence']:.0f}/100")
#         if savings is not None:
#             bits.append(f"savings: {_format_money(savings)}/mo")
#         lines.append("- " + " | ".join(str(b) for b in bits))

#     if len(hits) > 1 and any(h.row.get("monthly_savings") is not None for h in hits):
#         lines.append("")
#         lines.append(
#             f"**Combined monthly impact of these VMs: {_format_money(total_savings)}**"
#         )

#     return "\n".join(lines)


# def _try_llm_answer(question: str, hits: list[RetrievedVM]) -> str | None:
#     """
#     Optional LLM synthesis step. Returns None (triggering template fallback)
#     if no API key is configured or the call fails for any reason -- this
#     function must NEVER raise, since the chat feature has to keep working
#     without an LLM wired up.
#     """
#     client_info = _get_llm_client()
#     if not client_info:
#         return None
#     client, model = client_info

#     try:
#         context_lines = []
#         for h in hits:
#             r = h.row
#             context_lines.append(
#                 f"- {r.get('vm_id')}: action={r.get('action')}, "
#                 f"tier {r.get('current_tier')}->{r.get('recommended_tier')}, "
#                 f"risk={r.get('risk_level')}, profile={r.get('cluster_label')}, "
#                 f"confidence={r.get('confidence')}, "
#                 f"savings=${r.get('monthly_savings', 0):.0f}/mo, "
#                 f"reason: {r.get('reason', '')}"
#             )
#         context = "\n".join(context_lines)

#         prompt = (
#             "You are a cloud cost advisor. Answer the user's question using ONLY "
#             "the VM data below. Do not invent numbers or VMs not listed. Be concise.\n\n"
#             f"VM data:\n{context}\n\nQuestion: {question}\nAnswer:"
#         )

#         resp = client.chat.completions.create(
#             model=model,
#             messages=[{"role": "user", "content": prompt}],
#             temperature=0.2,
#             max_tokens=400,
#         )
#         return resp.choices[0].message.content.strip()
#     except Exception as e:
#         print(f"[LLM DEBUG] LLM call failed: {type(e).__name__} - {e}")  # TEMPORARY
#         return None  # any failure -> silently fall back to template mode


# def _detect_vm_id(question: str, known_vm_ids: list[str]) -> str | None:
#     """Returns the exact vm_id if mentioned verbatim in the question, else None."""
#     q = question.lower()
#     for vm_id in known_vm_ids:
#         if vm_id.lower() in q:
#             return vm_id
#     return None


# class AdvisorChat:
#     """
#     Main entry point for the "Ask the Advisor" feature.

#     Usage:
#         chat = AdvisorChat(recs_df)
#         answer, hits = chat.ask("which bursty VMs are high risk?")
#     """

#     def __init__(self, recs):
#         self.recs = recs
#         self.known_vm_ids = recs["vm_id"].tolist()
#         self.retriever = RecommendationRetriever(recs)

#     def ask(self, question: str, k: int = 8) -> tuple[str, list[RetrievedVM]]:
#         vm_id = _detect_vm_id(question, self.known_vm_ids)
#         if vm_id:
#             row = self.recs[self.recs["vm_id"] == vm_id].iloc[0]
#             hits = [RetrievedVM(vm_id=vm_id, score=1.0, row=row.to_dict())]
#             llm_answer = _try_llm_answer(question, hits)
#             answer = llm_answer if llm_answer else _template_answer(question, hits, {})
#             return answer, hits

#         filters = _detect_filters(
#             question
#         )  # now tries LLM first, falls back to keywords

#         if filters[
#             "actions"
#         ]:  # question implies multiple actions (e.g. "downsize and upsize")
#             hits = []
#             for action in filters["actions"]:
#                 hits.extend(
#                     self.retriever.filter_then_retrieve(
#                         question,
#                         k=k,
#                         action=action,
#                         risk_level=filters["risk_level"],
#                         cluster_label=filters["cluster_label"],
#                         min_confidence=filters["min_confidence"],
#                     )
#                 )
#         else:
#             hits = self.retriever.filter_then_retrieve(
#                 question,
#                 k=k,
#                 action=filters["action"],
#                 risk_level=filters["risk_level"],
#                 cluster_label=filters["cluster_label"],
#                 min_confidence=filters["min_confidence"],
#             )

#         if not hits:
#             hits = self.retriever.retrieve(question, k=k)

#         llm_answer = _try_llm_answer(question, hits) if hits else None
#         answer = llm_answer if llm_answer else _template_answer(question, hits, filters)
#         return answer, hits
# ------------------------------------
"""
autovm/model/rag_chat.py

"Ask the Advisor" chat engine: takes a free-form question, understands
intent (filters), retrieves relevant VMs via rag_retriever.py, and
synthesizes a grounded natural-language answer.

Intent detection -- two modes
------------------------------
1. LLM-based intent detection (NEW, preferred when an API key is available):
   the LLM reads the question and outputs structured filters as JSON
   (action/actions, risk_level, cluster_label, min_confidence). This
   understands synonyms, grammar variants, and phrasing the old keyword
   lists could never anticipate (e.g. "upsizing" == "upsize", "right-size"
   == either, "too big" == "downsize").
2. Keyword-based fallback (original, always available, no API key needed):
   simple substring matching against hardcoded keyword lists. Used
   automatically if no LLM key is set, or if the LLM intent call fails for
   any reason -- the chat feature must never break because of a missing
   or failing LLM.

Two answer modes (unchanged from before)
-----------------------------------------
1. Template mode (default, no API key needed): builds the answer directly
   from the retrieved rows using string templates. Always available,
   always grounded -- every number in the answer comes directly from your
   recommendations.csv, never invented.
2. LLM mode (optional): if an OpenAI-compatible API key is configured via
   environment variables, the retrieved rows are passed to an LLM as
   context and it writes a more natural-sounding summary. If the call
   fails or no key is set, this silently falls back to template mode --
   the chat feature never breaks because of a missing API key.

This keeps the "RAG" pattern intact (retrieve real data -> ground the
answer in it) regardless of whether an LLM is wired up.
"""

from __future__ import annotations

import json
import os
import re

from model.rag_retriever import RecommendationRetriever, RetrievedVM

# Intent keywords -> structured filter values. Used ONLY as a fallback when
# no LLM is available, or the LLM intent call fails. Checked against the
# lower-cased question text.
ACTION_KEYWORDS = {
    "downsize": [
        "downsize",
        "downsizing",
        "downsized",
        "shrink",
        "shrinking",
        "smaller",
        "reduce",
        "reducing",
    ],
    "upsize": [
        "upsize",
        "upsizing",
        "upsized",
        "upgrade",
        "upgrading",
        "bigger",
        "larger",
        "increase",
        "increasing",
    ],
    "keep": ["keep", "unchanged", "fine as", "already right"],
}
RISK_KEYWORDS = {
    "HIGH": ["high risk", "risky", "dangerous", "unsafe"],
    "MEDIUM": ["medium risk", "moderate risk"],
    "LOW": ["low risk", "safe", "safely"],
}
CLUSTER_KEYWORDS = {
    "idle": ["idle", "unused", "doing nothing"],
    "bursty": ["bursty", "spiky", "spikes", "burst"],
    "steady": ["steady", "stable", "consistent"],
    "seasonal/irregular": ["seasonal", "irregular", "periodic", "month-end"],
}

VALID_ACTIONS = {"downsize", "upsize", "keep"}
VALID_RISK_LEVELS = {"HIGH", "MEDIUM", "LOW"}
VALID_CLUSTERS = {"idle", "steady", "bursty", "seasonal/irregular"}


def _empty_filters() -> dict:
    return {
        "action": None,
        "actions": [],
        "risk_level": None,
        "cluster_label": None,
        "min_confidence": None,
    }


def _detect_filters_keywords(question: str) -> dict:
    """Original keyword-based fallback -- always available, no API key needed."""
    q = question.lower()
    filters = _empty_filters()

    matched_actions = []
    for action, kws in ACTION_KEYWORDS.items():
        if any(kw in q for kw in kws):
            matched_actions.append(action)

    if len(matched_actions) == 1:
        filters["action"] = matched_actions[0]
    elif len(matched_actions) > 1:
        filters["actions"] = matched_actions

    for risk, kws in RISK_KEYWORDS.items():
        if any(kw in q for kw in kws):
            filters["risk_level"] = risk
            break

    for cluster, kws in CLUSTER_KEYWORDS.items():
        if any(kw in q for kw in kws):
            filters["cluster_label"] = cluster
            break

    m = re.search(r"confidence\D{0,10}(\d{1,3})", q)
    if m:
        filters["min_confidence"] = float(m.group(1))

    return filters


def _get_llm_client():
    """
    Returns (client, model, base_url) if an LLM is configured, else None.
    Shared by both intent detection and answer generation so there's only
    one place that knows how to construct the client.
    """
    api_key = (
        os.environ.get("GROQ_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("AZURE_OPENAI_API_KEY")
    )
    if not api_key:
        return None

    base_url = (
        "https://api.groq.com/openai/v1" if os.environ.get("GROQ_API_KEY") else None
    )
    default_model = (
        "openai/gpt-oss-20b" if os.environ.get("GROQ_API_KEY") else "gpt-4o-mini"
    )
    model = os.environ.get("GROQ_MODEL", default_model)

    try:
        import openai

        client = openai.OpenAI(api_key=api_key, base_url=base_url)
        return client, model
    except Exception:
        return None


def _detect_filters_llm(question: str) -> dict | None:
    """
    NEW -- asks the LLM to interpret the question's intent and return
    structured filters as JSON. This understands synonyms and phrasing
    variants ("upsizing"/"upsize", "right-size", "too big", etc.) that a
    fixed keyword list can never fully anticipate.

    Returns None (triggering keyword fallback) if no LLM is available or
    the call/parsing fails for any reason -- this function must NEVER raise.
    """
    client_info = _get_llm_client()
    if not client_info:
        return None
    client, model = client_info

    prompt = (
        "Extract structured filters from the user's question about VM "
        "right-sizing recommendations. Respond with ONLY a JSON object, "
        "no other text, in this exact shape:\n"
        '{"actions": [...], "risk_level": "HIGH"|"MEDIUM"|"LOW"|null, '
        '"cluster_label": "idle"|"steady"|"bursty"|"seasonal/irregular"|null, '
        '"min_confidence": number|null}\n\n'
        "Rules:\n"
        '- "actions" is a list; include "downsize" if the question asks about '
        "downsizing/shrinking/reducing VMs (in any grammatical form, e.g. "
        '"downsizing", "right-sizing down", "too big"), include "upsize" if '
        'it asks about upsizing/upgrading/enlarging VMs, include "keep" if '
        "it asks about VMs that should stay unchanged. Include multiple "
        "values if the question asks about more than one (e.g. both "
        "downsize and upsize). Leave the list empty if no action is implied.\n"
        "- Only set risk_level/cluster_label/min_confidence if the question "
        "clearly implies them; otherwise use null.\n\n"
        f"Question: {question}\n"
        "JSON:"
    )

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,  # deterministic -- this is a parsing task, not creative writing
            max_tokens=200,
        )
        raw = resp.choices[0].message.content.strip()

        # Models sometimes wrap JSON in markdown code fences -- strip those if present
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())

        parsed = json.loads(raw)

        filters = _empty_filters()

        actions = [a for a in parsed.get("actions", []) if a in VALID_ACTIONS]
        if len(actions) == 1:
            filters["action"] = actions[0]
        elif len(actions) > 1:
            filters["actions"] = actions

        risk = parsed.get("risk_level")
        if risk in VALID_RISK_LEVELS:
            filters["risk_level"] = risk

        cluster = parsed.get("cluster_label")
        if cluster in VALID_CLUSTERS:
            filters["cluster_label"] = cluster

        conf = parsed.get("min_confidence")
        if isinstance(conf, (int, float)):
            filters["min_confidence"] = float(conf)

        return filters
    except Exception as e:
        print(
            f"[LLM INTENT DEBUG] LLM intent detection failed: {type(e).__name__} - {e}"
        )  # TEMPORARY
        return None  # any failure -> caller falls back to keyword detection


def _detect_filters(question: str) -> dict:
    """
    Main entry point for intent detection. Tries the LLM first (understands
    synonyms/phrasing), falls back to keyword matching if the LLM is
    unavailable or fails. Never returns None.
    """
    llm_filters = _detect_filters_llm(question)
    if llm_filters is not None:
        return llm_filters
    return _detect_filters_keywords(question)


def _format_money(x: float) -> str:
    return f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}"


def _template_answer(question: str, hits: list[RetrievedVM], filters: dict) -> str:
    """Builds a grounded natural-language answer directly from retrieved rows."""
    if not hits:
        return (
            "I couldn't find any VMs matching that question in the current "
            "recommendations. Try rephrasing, or check the Overview tab filters."
        )

    lines = []
    filt_desc = []
    if filters.get("action"):
        filt_desc.append(f"action = {filters['action']}")
    if filters.get("actions"):
        filt_desc.append(f"actions = {', '.join(filters['actions'])}")
    if filters.get("risk_level"):
        filt_desc.append(f"risk = {filters['risk_level']}")
    if filters.get("cluster_label"):
        filt_desc.append(f"behavior profile = {filters['cluster_label']}")
    if filters.get("min_confidence"):
        filt_desc.append(f"confidence >= {filters['min_confidence']:.0f}")

    header = f"Found {len(hits)} matching VM(s)"
    if filt_desc:
        header += f" ({', '.join(filt_desc)})"
    lines.append(header + ":")
    lines.append("")

    total_savings = 0.0
    for h in hits:
        r = h.row
        savings = r.get("monthly_savings")
        if savings is not None:
            total_savings += savings
        bits = [f"**{r['vm_id']}**"]
        if "action" in r:
            bits.append(f"action: {r['action']}")
        if "current_tier" in r and "recommended_tier" in r:
            bits.append(f"{r['current_tier']} -> {r['recommended_tier']}")
        if "risk_level" in r:
            bits.append(f"risk: {r['risk_level']}")
        if "cluster_label" in r and r.get("cluster_label"):
            bits.append(f"profile: {r['cluster_label']}")
        if "confidence" in r:
            bits.append(f"confidence: {r['confidence']:.0f}/100")
        if savings is not None:
            bits.append(f"savings: {_format_money(savings)}/mo")
        lines.append("- " + " | ".join(str(b) for b in bits))

    if len(hits) > 1 and any(h.row.get("monthly_savings") is not None for h in hits):
        lines.append("")
        lines.append(
            f"**Combined monthly impact of these VMs: {_format_money(total_savings)}**"
        )

    return "\n".join(lines)


def _try_llm_answer(question: str, hits: list[RetrievedVM]) -> str | None:
    """
    Optional LLM synthesis step. Returns None (triggering template fallback)
    if no API key is configured or the call fails for any reason -- this
    function must NEVER raise, since the chat feature has to keep working
    without an LLM wired up.
    """
    client_info = _get_llm_client()
    if not client_info:
        return None
    client, model = client_info

    try:
        context_lines = []
        for h in hits:
            r = h.row
            context_lines.append(
                f"- {r.get('vm_id')}: action={r.get('action')}, "
                f"tier {r.get('current_tier')}->{r.get('recommended_tier')}, "
                f"risk={r.get('risk_level')}, profile={r.get('cluster_label')}, "
                f"confidence={r.get('confidence')}, "
                f"savings=${r.get('monthly_savings', 0):.0f}/mo, "
                f"reason: {r.get('reason', '')}"
            )
        context = "\n".join(context_lines)

        prompt = (
            "You are a cloud cost advisor. Answer the user's question using ONLY "
            "the VM data below. Do not invent numbers or VMs not listed. Be concise.\n\n"
            f"VM data:\n{context}\n\nQuestion: {question}\nAnswer:"
        )

        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=400,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"[LLM DEBUG] LLM call failed: {type(e).__name__} - {e}")  # TEMPORARY
        return None  # any failure -> silently fall back to template mode


def _detect_vm_ids(question: str, known_vm_ids: list[str]) -> list[str]:
    """
    Returns ALL exact vm_ids mentioned verbatim in the question, not just
    the first one -- a question like "details on vm-a and vm-b" must
    return both, not silently drop vm-b.
    """
    q = question.lower()
    matches = [vm_id for vm_id in known_vm_ids if vm_id.lower() in q]
    return matches


class AdvisorChat:
    """
    Main entry point for the "Ask the Advisor" feature.

    Usage:
        chat = AdvisorChat(recs_df)
        answer, hits = chat.ask("which bursty VMs are high risk?")
    """

    def __init__(self, recs):
        self.recs = recs
        self.known_vm_ids = recs["vm_id"].tolist()
        self.retriever = RecommendationRetriever(recs)

    def ask(self, question: str, k: int = 8) -> tuple[str, list[RetrievedVM]]:
        matched_vm_ids = _detect_vm_ids(
            question, self.known_vm_ids
        )  # CHANGED -- all matches, not just one
        if matched_vm_ids:
            hits = []
            for vm_id in matched_vm_ids:
                row = self.recs[self.recs["vm_id"] == vm_id].iloc[0]
                hits.append(RetrievedVM(vm_id=vm_id, score=1.0, row=row.to_dict()))
            llm_answer = _try_llm_answer(question, hits)
            answer = llm_answer if llm_answer else _template_answer(question, hits, {})
            return answer, hits

        filters = _detect_filters(
            question
        )  # now tries LLM first, falls back to keywords

        if filters[
            "actions"
        ]:  # question implies multiple actions (e.g. "downsize and upsize")
            hits = []
            for action in filters["actions"]:
                hits.extend(
                    self.retriever.filter_then_retrieve(
                        question,
                        k=k,
                        action=action,
                        risk_level=filters["risk_level"],
                        cluster_label=filters["cluster_label"],
                        min_confidence=filters["min_confidence"],
                    )
                )
        else:
            hits = self.retriever.filter_then_retrieve(
                question,
                k=k,
                action=filters["action"],
                risk_level=filters["risk_level"],
                cluster_label=filters["cluster_label"],
                min_confidence=filters["min_confidence"],
            )

        if not hits:
            hits = self.retriever.retrieve(question, k=k)

        llm_answer = _try_llm_answer(question, hits) if hits else None
        answer = llm_answer if llm_answer else _template_answer(question, hits, filters)
        return answer, hits
