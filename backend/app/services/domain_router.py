import logging
from functools import lru_cache

from app.services.embeddings import embed_texts, similarity

log = logging.getLogger("domain_router")

_DOMAINS = {
    "biomedical": (
        "biomedical, medical, clinical, veterinary, animal health, livestock, "
        "disease, diagnosis, epidemiology and public health research"
    ),
    "cs_ml": (
        "computer science, machine learning, artificial intelligence, algorithms, "
        "software engineering, neural networks and data engineering"
    ),
    "physical": (
        "physics, chemistry, materials science, engineering, energy, "
        "earth science and climate science"
    ),
    "social": (
        "economics, finance, law, policy, education, business, "
        "management and social science"
    ),
}

_AMBIGUITY_MARGIN = 0.03


@lru_cache(maxsize=1)
def _domain_vecs() -> dict[str, list[float]]:
    keys = list(_DOMAINS)
    vecs = embed_texts([_DOMAINS[k] for k in keys])
    return dict(zip(keys, vecs))


def classify_text(text: str) -> tuple[str, bool, dict[str, float]]:
    """Returns (best_domain, is_ambiguous, scores). Never raises."""
    text = (text or "").strip()
    if not text:
        return "unknown", True, {}
    try:
        qvec = embed_texts([text])[0]
        scores = {k: float(similarity(qvec, v)) for k, v in _domain_vecs().items()}
    except Exception:
        log.exception("domain classification failed")
        return "unknown", True, {}

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best, best_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else -1.0
    return best, (best_score - second_score) < _AMBIGUITY_MARGIN, scores


def route_providers(text: str) -> dict[str, bool]:
    """Errors and ambiguity fall back to the broader search (both providers on)."""
    domain, ambiguous, _ = classify_text(text)
    if domain == "unknown" or ambiguous:
        return {"europepmc": True, "arxiv": True}
    if domain == "biomedical":
        return {"europepmc": True, "arxiv": False}
    return {"europepmc": False, "arxiv": True}


_REPORT_TYPES = {
    "field_survey": (
        "field survey or field investigation: samples or observations collected from animals, farms, "
        "households, communities or sites, reporting counts, positivity rates and prevalence"
    ),
    "scientific_research": (
        "scientific research study or experiment with a hypothesis, laboratory methods, "
        "statistical analysis, results and discussion against published literature"
    ),
    "business_operational": (
        "business or operational report on strategy, market, performance, KPIs, "
        "processes, stakeholders and efficiency"
    ),
    "financial_ledger": (
        "financial or accounting report: ledger, transactions, debits and credits, "
        "reconciliation, budget, revenue, expenditure and audit"
    ),
    "technical_project": (
        "technical or engineering project report on system architecture, implementation, "
        "deployment, specification, development milestones and evaluation"
    ),
}
_REPORT_MIN_SCORE = 0.25   # tune from the logged scores
_REPORT_MARGIN = 0.01


@lru_cache(maxsize=1)
def _report_type_vecs() -> dict[str, list[float]]:
    keys = list(_REPORT_TYPES)
    return dict(zip(keys, embed_texts([_REPORT_TYPES[k] for k in keys])))


def classify_report_type(text: str) -> str | None:
    """Returns a report type, or None (caller falls back to 'general'). Never raises."""
    text = (text or "").strip()[:1500]
    if not text:
        return None
    try:
        qvec = embed_texts([text])[0]
        scores = {k: float(similarity(qvec, v)) for k, v in _report_type_vecs().items()}
    except Exception:
        log.exception("report type classification failed")
        return None
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    log.info("report_type scores=%s", {k: round(v, 3) for k, v in ranked})
    (best, s1), (_, s2) = ranked[0], ranked[1]
    if s1 < _REPORT_MIN_SCORE or (s1 - s2) < _REPORT_MARGIN:
        return None
    return best