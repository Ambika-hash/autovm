# """
# autovm/model/rag_retriever.py

# Retrieval layer for the "Ask the Advisor" chat feature.

# Turns each row of recommendations.csv (produced by recommender.py) into a
# small text "document", indexes all documents with TF-IDF, and retrieves the
# most relevant VMs for a free-form question.

# Why TF-IDF instead of embeddings/vector DB
# -------------------------------------------
# Your fleet is a few hundred to a few thousand VMs, not millions of documents.
# TF-IDF + cosine similarity (scikit-learn, already in your requirements.txt)
# is fast, needs no external model download, no API key, and no vector
# database -- appropriate for this data size. If your fleet grows into the
# tens of thousands of VMs, swapping this for a proper embedding index later
# is a drop-in replacement (same retrieve() interface).

# This module does ONLY retrieval -- "which VMs are relevant to this
# question, and what do we know about them". Answer generation (turning
# retrieved rows into a natural-language sentence) lives in rag_chat.py.
# """

# from __future__ import annotations

# from dataclasses import dataclass

# import numpy as np
# import pandas as pd
# from sklearn.feature_extraction.text import TfidfVectorizer
# from sklearn.metrics.pairwise import cosine_similarity

# # Columns used to build the searchable text per VM. Falls back gracefully
# # if some (e.g. cluster_label) aren't present yet.
# TEXT_COLUMNS_PRIORITY = [
#     "vm_id", "current_tier", "recommended_tier", "action", "risk_level",
#     "cluster_label", "binding_resource", "reason",
# ]

# # Numeric columns worth surfacing verbatim in retrieved context (not just
# # embedded as text) so the answer generator can quote exact numbers.
# NUMERIC_CONTEXT_COLUMNS = [
#     "monthly_savings", "annual_savings", "confidence", "failure_risk",
#     "burst_ratio", "safety_buffer_used",
# ]


# @dataclass
# class RetrievedVM:
#     vm_id: str
#     score: float
#     row: dict


# def _row_to_document(row: pd.Series) -> str:
#     """Flatten one VM's recommendation row into a text blob for TF-IDF."""
#     parts = []
#     for col in TEXT_COLUMNS_PRIORITY:
#         if col in row.index and pd.notna(row[col]):
#             parts.append(str(row[col]))
#     # Add numeric context as words too, e.g. "risk_level HIGH" style phrases
#     # help short queries like "high risk vms" match better.
#     for col in NUMERIC_CONTEXT_COLUMNS:
#         if col in row.index and pd.notna(row[col]):
#             parts.append(f"{col} {row[col]:.2f}")
#     return " ".join(parts)


# class RecommendationRetriever:
#     """
#     Build once per app session (cache it), reuse across questions.

#     Usage:
#         retriever = RecommendationRetriever(recs_df)
#         hits = retriever.retrieve("which bursty vms are high risk", k=5)
#     """

#     def __init__(self, recs: pd.DataFrame):
#         if recs.empty:
#             raise ValueError("No recommendations to index -- recs dataframe is empty.")
#         self.recs = recs.reset_index(drop=True)
#         self.documents = self.recs.apply(_row_to_document, axis=1).tolist()

#         self.vectorizer = TfidfVectorizer(
#             stop_words="english",
#             ngram_range=(1, 2),   # catches two-word phrases like "high risk", "bursty vm"
#             min_df=1,
#         )
#         self.doc_matrix = self.vectorizer.fit_transform(self.documents)

#     def retrieve(self, query: str, k: int = 5) -> list[RetrievedVM]:
#         """Return the top-k most relevant VMs for a free-form query."""
#         query_vec = self.vectorizer.transform([query])
#         scores = cosine_similarity(query_vec, self.doc_matrix).flatten()
#         top_idx = np.argsort(scores)[::-1][:k]

#         results = []
#         for i in top_idx:
#             if scores[i] <= 0:
#                 continue   # don't return completely irrelevant matches
#             row = self.recs.iloc[i]
#             results.append(RetrievedVM(vm_id=row["vm_id"], score=float(scores[i]), row=row.to_dict()))
#         return results

#     def filter_then_retrieve(
#         self,
#         query: str,
#         k: int = 10,
#         action: str | None = None,
#         risk_level: str | None = None,
#         cluster_label: str | None = None,
#         min_confidence: float | None = None,
#     ) -> list[RetrievedVM]:
#         """
#         Hybrid search: apply hard structured filters FIRST (exact match on
#         action/risk/cluster), THEN rank what's left by text relevance.

#         This matters for questions like "which VMs are safe to downsize" --
#         a pure text-similarity search might miss VMs whose `reason` text
#         doesn't literally contain the word "safe", but a structured filter
#         on action="downsize" + risk_level="LOW" catches them reliably.
#         """
#         subset = self.recs
#         if action:
#             subset = subset[subset["action"] == action]
#         if risk_level:
#             subset = subset[subset["risk_level"] == risk_level]
#         if cluster_label and "cluster_label" in subset.columns:
#             subset = subset[subset["cluster_label"] == cluster_label]
#         if min_confidence is not None:
#             subset = subset[subset["confidence"] >= min_confidence]

#         if subset.empty:
#             return []

#         if query.strip():
#             sub_retriever = RecommendationRetriever(subset)
#             return sub_retriever.retrieve(query, k=k)
#         else:
#             # no text query -- just return the filtered rows, ranked by $ impact
#             subset = subset.reindex(subset["monthly_savings"].abs().sort_values(ascending=False).index)
#             return [
#                 RetrievedVM(vm_id=r["vm_id"], score=1.0, row=r.to_dict())
#                 for _, r in subset.head(k).iterrows()
#             ]
# -----------------------------------
"""
autovm/model/rag_retriever.py

Retrieval layer for the "Ask the Advisor" chat feature.

Turns each row of recommendations.csv (produced by recommender.py) into a
small text "document", indexes all documents with TF-IDF, and retrieves the
most relevant VMs for a free-form question.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

TEXT_COLUMNS_PRIORITY = [
    "vm_id",
    "current_tier",
    "recommended_tier",
    "action",
    "risk_level",
    "cluster_label",
    "binding_resource",
    "reason",
]

NUMERIC_CONTEXT_COLUMNS = [
    "monthly_savings",
    "annual_savings",
    "confidence",
    "failure_risk",
    "burst_ratio",
    "safety_buffer_used",
]


@dataclass
class RetrievedVM:
    vm_id: str
    score: float
    row: dict


def _row_to_document(row: pd.Series) -> str:
    parts = []
    for col in TEXT_COLUMNS_PRIORITY:
        if col in row.index and pd.notna(row[col]):
            parts.append(str(row[col]))
    for col in NUMERIC_CONTEXT_COLUMNS:
        if col in row.index and pd.notna(row[col]):
            parts.append(f"{col} {row[col]:.2f}")
    return " ".join(parts)


class RecommendationRetriever:
    def __init__(self, recs: pd.DataFrame):
        if recs.empty:
            raise ValueError("No recommendations to index -- recs dataframe is empty.")
        self.recs = recs.reset_index(drop=True)
        self.documents = self.recs.apply(_row_to_document, axis=1).tolist()

        self.vectorizer = TfidfVectorizer(
            stop_words="english",
            ngram_range=(1, 2),
            min_df=1,
        )
        self.doc_matrix = self.vectorizer.fit_transform(self.documents)

    def retrieve(self, query: str, k: int = 5) -> list[RetrievedVM]:
        query_vec = self.vectorizer.transform([query])
        scores = cosine_similarity(query_vec, self.doc_matrix).flatten()
        top_idx = np.argsort(scores)[::-1][:k]

        results = []
        for i in top_idx:
            if scores[i] <= 0:
                continue
            row = self.recs.iloc[i]
            results.append(
                RetrievedVM(
                    vm_id=row["vm_id"], score=float(scores[i]), row=row.to_dict()
                )
            )
        return results

    def filter_then_retrieve(
        self,
        query: str,
        k: int = 10,
        action: str | None = None,
        risk_level: str | None = None,
        cluster_label: str | None = None,
        min_confidence: float | None = None,
    ) -> list[RetrievedVM]:
        """
        Hybrid search: apply hard structured filters FIRST (exact match on
        action/risk/cluster), THEN rank what's left by text relevance.

        FIXED: if the hard filters already narrowed the subset down
        correctly, but the text-similarity re-ranking finds zero matches
        (e.g. because the question used a word like "upsizing" that
        doesn't tokenize the same as "upsize"), fall back to returning the
        filtered subset instead of discarding an already-correct result.
        """
        subset = self.recs
        if action:
            subset = subset[subset["action"] == action]
        if risk_level:
            subset = subset[subset["risk_level"] == risk_level]
        if cluster_label and "cluster_label" in subset.columns:
            subset = subset[subset["cluster_label"] == cluster_label]
        if min_confidence is not None:
            subset = subset[subset["confidence"] >= min_confidence]

        if subset.empty:
            return []

        def _subset_as_hits():
            ranked = subset.reindex(
                subset["monthly_savings"].abs().sort_values(ascending=False).index
            )
            return [
                RetrievedVM(vm_id=r["vm_id"], score=1.0, row=r.to_dict())
                for _, r in ranked.head(k).iterrows()
            ]

        if query.strip():
            sub_retriever = RecommendationRetriever(subset)
            text_hits = sub_retriever.retrieve(query, k=k)
            if text_hits:
                return text_hits
            # text ranking found nothing, but hard filters already narrowed
            # correctly -- return the filtered subset instead of nothing
            return _subset_as_hits()
        else:
            return _subset_as_hits()
