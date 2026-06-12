from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from docpilot.search.models import SearchResult


@dataclass
class QueryCase:
    """Single evaluation case: a query and the set of document basenames expected in results."""

    query: str
    relevant_sources: set[str]


@dataclass
class EvalReport:
    precision: dict[int, float]  # k -> mean P@k
    recall: dict[int, float]     # k -> mean R@k
    mrr: float
    n_queries: int

    def __str__(self) -> str:
        lines = [f"EvalReport (n={self.n_queries})"]
        for k in sorted(self.precision):
            lines.append(f"  P@{k}={self.precision[k]:.3f}  R@{k}={self.recall[k]:.3f}")
        lines.append(f"  MRR={self.mrr:.3f}")
        return "\n".join(lines)


SearchFn = Callable[[str], list[SearchResult]]


def precision_at_k(results: list[SearchResult], relevant: set[str], k: int) -> float:
    """Unique relevant documents found in top-k chunks divided by k."""
    top = results[:k]
    found = {Path(r.source).name for r in top} & relevant
    return len(found) / k if k else 0.0


def recall_at_k(results: list[SearchResult], relevant: set[str], k: int) -> float:
    """Fraction of relevant documents found in top-k chunks."""
    if not relevant:
        return 0.0
    top = results[:k]
    found = {Path(r.source).name for r in top} & relevant
    return len(found) / len(relevant)


def mrr(results: list[SearchResult], relevant: set[str]) -> float:
    """Reciprocal rank of the first relevant chunk."""
    for i, r in enumerate(results, 1):
        if Path(r.source).name in relevant:
            return 1.0 / i
    return 0.0


def evaluate(
    cases: list[QueryCase],
    search_fn: SearchFn,
    ks: list[int] | None = None,
) -> EvalReport:
    """Run all cases with search_fn and return mean metrics."""
    if ks is None:
        ks = [1, 3, 5]

    p_sums: dict[int, float] = {k: 0.0 for k in ks}
    r_sums: dict[int, float] = {k: 0.0 for k in ks}
    mrr_sum = 0.0

    for case in cases:
        results = search_fn(case.query)
        for k in ks:
            p_sums[k] += precision_at_k(results, case.relevant_sources, k)
            r_sums[k] += recall_at_k(results, case.relevant_sources, k)
        mrr_sum += mrr(results, case.relevant_sources)

    n = len(cases)
    return EvalReport(
        precision={k: p_sums[k] / n for k in ks},
        recall={k: r_sums[k] / n for k in ks},
        mrr=mrr_sum / n,
        n_queries=n,
    )
