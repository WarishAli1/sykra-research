import asyncio
import re
from collections import Counter
from app.agents.research_engine import (
    assess_coverage,
    derive_research_needs,
    merge_duplicate_papers,
    uncovered_needs,
)
from app.agents.state import AgentState

from app.services.paper_search import (
    fetch_openalex_works_by_ids_async,
    fetch_referenced_work_ids_async,
    sanitize_openalex_search,
    search_arxiv_async,
    search_arxiv_by_title_async,
    search_openalex_async,
    search_openalex_by_title_async,
    search_openalex_foundational_async,
    search_semantic_scholar_async,
)

from app.services.web_search import search_web_async

from app.services.embeddings import embed_texts, similarity
from app.services.embedding_cache import batch_get_or_compute

from app.services import request_dedup
from app.services import semantic_cache

from app.services.provider_capabilities import (
    providers_for_capabilities,
    web_source_intent_for_capabilities,
)

from app.config import settings


try:
    from app.services.provider_health import is_available as _provider_is_available
except Exception:
    def _provider_is_available(provider: str) -> bool:
        return True


MAX_TOTAL_CANDIDATES = 90

BASE_SIM_THRESH_FAST = 0.38
BASE_SIM_THRESH_RESEARCH = 0.32

_QUOTED_RE = re.compile(r'"([^"]+)"')


_BUDGETS = {
    "fast": {
        "openalex": 2,
        "arxiv": 1,
        "web": 1,
        "total": 3,
    },
    "research": {
        "openalex": 7,
        "arxiv": 3,
        "web": 1,
        "total": 11,
    },
}


class SearchMetrics:
    def __init__(self):
        self.openalex = 0
        self.arxiv = 0
        self.web = 0
        self.total = 0

    def can_search(
        self,
        provider: str,
        count: int,
        maxes: dict,
    ) -> bool:
        if self.total + count > maxes["total"]:
            return False

        if provider in ("openalex", "foundational", "backtrack"):
            return self.openalex + count <= maxes["openalex"]

        if provider == "arxiv":
            return self.arxiv + count <= maxes["arxiv"]

        if provider == "web":
            return self.web + count <= maxes["web"]

        return True

    def record(
        self,
        provider: str,
        count: int = 1,
    ) -> None:
        if provider in ("openalex", "foundational", "backtrack"):
            self.openalex += count

        elif provider == "arxiv":
            self.arxiv += count

        elif provider == "web":
            self.web += count

        self.total += count


def _safe_results(result) -> list[dict]:
    if isinstance(result, Exception):
        return []

    return result or []


def _get_plan(state: AgentState) -> dict:
    """
    Return the RetrievalPlan from state.

    This fallback is intentionally minimal.

    It must not reinterpret AnswerSpec.
    retrieval_plan_node.py is the only real retrieval planner.
    """
    plan = state.get("retrieval_plan") or {}

    if plan.get("intents"):
        return plan

    return {
        "intents": [
            {
                "query": state.get("query", ""),
                "purpose": "requirement",
                "priority": 1,
                "source_capabilities": [
                    "secondary_research"
                ],
            }
        ],
        "primary_source_required": False,
        "freshness_required": False,
        "use_foundational_search": False,
        "use_citation_backtracking": False,
        "max_search_intents": 1,
    }


def _extract_quoted_title(query: str) -> str | None:
    match = _QUOTED_RE.search(query or "")

    if not match:
        return None

    return match.group(1).strip()


def _normalize_title_strict(title: str) -> str:
    """
    Strict title normalization.

    Do NOT remove discriminating words such as:
    - revisiting
    - survey
    - review
    - analysis

    Those words are important for conservative primary-source detection.
    """
    t = (title or "").lower()

    t = re.sub(
        r"[^\w\s]",
        " ",
        t,
    )

    t = re.sub(
        r"\s+",
        " ",
        t,
    ).strip()

    return t


def _expected_canonical_titles(plan: dict) -> list[str]:
    titles = []

    for intent in plan.get("intents", []):
        if intent.get("purpose") != "canonical_source":
            continue

        title = _extract_quoted_title(
            str(intent.get("query") or "")
        )

        if title:
            titles.append(title)

    return list(dict.fromkeys(titles))


def _verify_primary_sources(
    candidates: list[dict],
    plan: dict,
) -> None:
    """
    Conservative primary-source detection.

    A paper is marked primary only when its normalized title exactly equals
    an expected canonical title from the RetrievalPlan.
    """
    expected_titles = _expected_canonical_titles(plan)

    if not expected_titles:
        return

    expected_normalized = {
        _normalize_title_strict(title)
        for title in expected_titles
        if title
    }

    for paper in candidates:
        paper_title = _normalize_title_strict(
            paper.get("title", "")
        )

        if paper_title in expected_normalized:
            paper["_primary_candidate"] = True
            paper["_source_role"] = "primary"
            paper["_primary_source_score"] = 1.0

        else:
            paper["_primary_candidate"] = False

            if paper.get("_source_role") == "primary":
                paper["_source_role"] = "secondary"

            paper.pop("_primary_source_score", None)


def _all_capabilities(plan: dict) -> set[str]:
    capabilities = set()

    for intent in plan.get("intents", []):
        capabilities.update(
            intent.get("source_capabilities", [])
        )

    return capabilities


async def _fetch_intent(
    intent: dict,
    maxes: dict,
    metrics: SearchMetrics,
    web_intent: str,
    min_year: int | None = None,
    max_year: int | None = None,
) -> list[dict]:
    query = str(intent.get("query") or "").strip()
    if not query:
        return []

    purpose = str(intent.get("purpose") or "requirement")
    capabilities = set(intent.get("source_capabilities") or [])
    if not capabilities:
        capabilities = {"secondary_research"}

    web_query = query
    if capabilities.intersection({
        "official_authority",
        "official_authority_financial",
        "official_authority_legal",
        "official_authority_clinical",
    }):
        web_query = (
            f"{query} site:worldbank.org OR site:adb.org OR "
            f"site:iea.org OR site:imf.org OR site:un.org OR site:who.int"
        )


    providers = providers_for_capabilities(capabilities)
    providers = {
        provider
        for provider in providers
        if _provider_is_available(provider)
    }
    if not providers:
        return []

    tasks = []
    title = (
        _extract_quoted_title(query)
        if purpose == "canonical_source"
        else None
    )

    if title:
        if (
            "openalex" in providers
            and metrics.can_search("openalex", 1, maxes)
        ):
            tasks.append(search_openalex_by_title_async(title, 3))
            metrics.record("openalex")
        if (
            "arxiv" in providers
            and metrics.can_search("arxiv", 1, maxes)
        ):
            tasks.append(search_arxiv_by_title_async(title, 3))
            metrics.record("arxiv")
        if (
            "web" in providers
            and metrics.can_search("web", 1, maxes)
        ):
            tasks.append(
                search_web_async(
                    web_query,
                    web_intent,
                    max_results=3,
                )
            )
            metrics.record("web")
    else:
        apply_year_filter = (
            min_year is not None
            or max_year is not None
        ) and purpose not in ("canonical_source", "equation")

        if (
            "openalex" in providers
            and metrics.can_search("openalex", 1, maxes)
        ):
            tasks.append(
                search_openalex_async(
                    query,
                    5,
                    purpose in ("canonical_source", "equation"),
                    min_year=min_year if apply_year_filter else None,
                    max_year=max_year if apply_year_filter else None,
                )
            )
            metrics.record("openalex")
        if (
            "arxiv" in providers
            and metrics.can_search("arxiv", 1, maxes)
        ):
            tasks.append(
                search_arxiv_async(
                    query,
                    4,
                )
            )
            metrics.record("arxiv")
        if (
            "web" in providers
            and metrics.can_search("web", 1, maxes)
        ):
            tasks.append(
                search_web_async(
                    web_query,
                    web_intent,
                    max_results=3,
                )
            )
            metrics.record("web")

    if not tasks:
        return []

    results = await asyncio.gather(
        *tasks,
        return_exceptions=True,
    )
    rows: list[dict] = []
    for result in results:
        rows.extend(_safe_results(result))

    for paper in rows:
        paper["_source_term"] = query
        paper["_retrieval_purpose"] = purpose
        paper["_primary_candidate"] = False

    return rows


async def _retrieve_foundational_budgeted(
    intents: list[dict],
    maxes: dict,
    metrics: SearchMetrics,
) -> list[dict]:
    if not _provider_is_available("openalex"):
        return []

    terms = []
    for intent in intents:
        if intent.get("purpose") not in (
            "canonical_source",
            "equation",
            "requirement",
        ):
            continue
        raw_query = str(intent.get("query") or "")
        title = _extract_quoted_title(raw_query)
        query = title or raw_query
        sanitized = sanitize_openalex_search(query, max_words=6)
        if sanitized:
            terms.append(sanitized)

    terms = list(dict.fromkeys(terms))[:2]
    if not terms:
        return []

    rows = []
    for term in terms:
        if not metrics.can_search("foundational", 1, maxes):
            break
        metrics.record("foundational")
        try:
            oa_result, s2_result = await asyncio.gather(
                search_openalex_foundational_async(term, 5),
                search_semantic_scholar_async(
                    term, limit=5, sort_by_citations=True
                ),
                return_exceptions=True,
            )
        except Exception:
            oa_result, s2_result = [], []

        for paper in _safe_results(oa_result):
            paper["_foundational_candidate"] = True
            paper["_foundational_source"] = "citation_sort"
            paper["_source_term"] = term
            rows.append(paper)

        for paper in _safe_results(s2_result):
            paper["_foundational_candidate"] = True
            paper["_foundational_source"] = "influential_sort"
            paper["_source_term"] = term
            rows.append(paper)

    return rows


async def _citation_backtrack_budgeted(
    candidates: list[dict],
    maxes: dict,
    metrics: SearchMetrics,
) -> list[dict]:
    if not _provider_is_available("openalex"):
        return []

    anchors = [
        paper.get("openalex_id")
        for paper in candidates
        if paper.get("openalex_id")
    ][:1]

    if not anchors:
        return []

    if not metrics.can_search("backtrack", 2, maxes):
        return []

    try:
        refs = await fetch_referenced_work_ids_async(anchors[0], 15)

    except Exception:
        refs = []

    metrics.record("backtrack", 1)

    ref_ids = []

    for wid in refs or []:
        if wid not in ref_ids:
            ref_ids.append(wid)

        if len(ref_ids) >= 8:
            break

    if not ref_ids:
        return []

    if not metrics.can_search("backtrack", 1, maxes):
        return []

    try:
        works = await fetch_openalex_works_by_ids_async(
            ref_ids,
            limit=8,
        )

    except Exception:
        return []

    metrics.record("backtrack", 1)

    rows = []

    for paper in _safe_results(works):
        paper["_foundational_candidate"] = True
        paper["_foundational_source"] = "citation_backtrack"
        paper["_source_term"] = "citation_backtrack"

        rows.append(paper)

    return rows


async def _foundational_convergence_budgeted(
    candidates: list[dict],
    maxes: dict,
    metrics: SearchMetrics,
) -> list[dict]:
    """
    Connected Papers-style "prior works" discovery. Pure code, no LLM.

    Intersects the reference lists of the top relevant papers: a work
    that several independent papers ALL cite is very likely the
    foundational origin of the topic — even when the topic is not in
    FOUNDATIONAL_PAPERS and even when a survey out-cites the origin.

    Budget-adaptive: uses as many anchors (2-3) as budget allows.
    """
    if not _provider_is_available("openalex"):
        return []

    anchors = [
        paper.get("openalex_id")
        for paper in sorted(
            candidates,
            key=lambda p: p.get("_initial_sim", 0),
            reverse=True,
        )
        if paper.get("openalex_id")
        and not paper.get("_foundational_candidate")
    ]
    anchors = list(dict.fromkeys(anchors))[:3]

    affordable = min(
        3,
        max(0, maxes["openalex"] - metrics.openalex - 1),
        max(0, maxes["total"] - metrics.total - 1),
    )
    if affordable < 2:
        return []
    anchors = anchors[:affordable]
    if len(anchors) < 2:
        return []

    metrics.record("backtrack", len(anchors))
    ref_lists = await asyncio.gather(
        *[fetch_referenced_work_ids_async(oid, 40) for oid in anchors],
        return_exceptions=True,
    )
    ref_sets = [
        set(refs)
        for refs in ref_lists
        if isinstance(refs, list) and refs
    ]
    if len(ref_sets) < 2:
        return []

    counts = Counter()
    for ref_set in ref_sets:
        counts.update(ref_set)

    common = [
        wid for wid, cnt in counts.items() if cnt >= 2
    ][:12]
    if not common:
        return []

    if not metrics.can_search("backtrack", 1, maxes):
        return []
    metrics.record("backtrack", 1)
    try:
        works = await fetch_openalex_works_by_ids_async(common, 12)
    except Exception:
        return []

    hit_map = {wid: counts[wid] for wid in common}
    rows = []
    for paper in _safe_results(works):
        paper["_foundational_candidate"] = True
        paper["_foundational_source"] = "citation_convergence"
        paper["_source_term"] = "citation_convergence"
        paper["_convergence_hits"] = hit_map.get(
            paper.get("openalex_id", ""), 0
        )
        rows.append(paper)

    print(
        f"[search] convergence discovery: {len(anchors)} anchors -> "
        f"{len(rows)} common-ancestor candidates"
    )
    return rows


async def _embed_candidates(
    candidates: list[dict],
    query_embedding: list[float],
) -> None:
    missing = [
        paper
        for paper in candidates
        if paper.get("abstract_vec") is None
    ]

    if not missing:
        return

    paired = await asyncio.to_thread(
        batch_get_or_compute,
        missing[:MAX_TOTAL_CANDIDATES],
        embed_texts,
    )

    for paper, vec in paired:
        paper["_initial_sim"] = similarity(
            query_embedding,
            vec,
        )

        paper["abstract_vec"] = vec


async def _materialize_cached_search(
    state: AgentState,
    cached: dict,
) -> dict:

    raw = merge_duplicate_papers(cached.get("raw_search_results", []) or [])
    query_embedding = cached.get("query_embedding")

    if not query_embedding:
        query_embedding = (
            await asyncio.to_thread(
                embed_texts,
                [state["query"]],
            )
        )[0]

    paired = await asyncio.to_thread(
        batch_get_or_compute,
        raw[:MAX_TOTAL_CANDIDATES],
        embed_texts,
    )

    for paper, vec in paired:
        paper["_initial_sim"] = similarity(
            query_embedding,
            vec,
        )

        paper["abstract_vec"] = vec

    combined = [p for p, _ in paired]

    _verify_primary_sources(
        combined,
        state.get("retrieval_plan") or {},
    )

    needs = derive_research_needs(
        state.get("query", ""),
        state.get("query_understanding") or {},
        state.get("report_plan") or {},
    )

    coverage = assess_coverage(needs, combined)

    return {
        "raw_search_results": combined,
        "search_attempts": state.get("search_attempts", 0) + 1,
        "needs_retry": False,
        "query_embedding": query_embedding,
        "search_cache_hit": True,
        "term_coverage": coverage,
    }


async def _search_core_async(
    state: AgentState,
    scope: str,
) -> dict:
    mode = state.get("response_mode", "normal")
    evidence_mode = state.get("evidence_mode", "literature")

    is_fast = mode not in ("researched", "graph_research")

    target_k = int(
        state.get("target_paper_k")
        or settings.TOP_K_PAPERS_MAX
    )

    plan = _get_plan(state)

    maxes = _BUDGETS["fast"] if is_fast else _BUDGETS["research"]

    metrics = SearchMetrics()

    all_capabilities = _all_capabilities(plan)

    web_intent = web_source_intent_for_capabilities(
        all_capabilities
    )

    intents = sorted(
        plan.get("intents", []),
        key=lambda x: (
            int(x.get("priority", 1) or 1),
            x.get("purpose") == "canonical_source",
        ),
        reverse=True,
    )

    evidence_contract = state.get("evidence_contract") or {}
    min_year = None
    max_year = None
    for c in evidence_contract.get("constraints", []):
        if c.get("field") == "publication_year":
            try:
                val = int(c.get("value", 0))
            except (ValueError, TypeError):
                continue
            if c.get("operator") == "gte":
                min_year = val
            elif c.get("operator") == "lte":
                max_year = val

    max_intents = int(
        plan.get("max_search_intents")
        or (3 if is_fast else 4)
    )

    intents = intents[:max_intents]

    all_rows: list[dict] = []

    for intent in intents:
        if metrics.total >= maxes["total"]:
            break
        rows = await _fetch_intent(
            intent,
            maxes,
            metrics,
            web_intent,
            min_year=min_year,
            max_year=max_year,
        )

        all_rows.extend(rows)

    all_rows = merge_duplicate_papers(all_rows)

    if plan.get("use_foundational_search"):
        foundational_rows = await _retrieve_foundational_budgeted(
            intents,
            maxes,
            metrics,
        )

        if foundational_rows:
            all_rows = merge_duplicate_papers(
                all_rows + foundational_rows
            )

    answer_spec = state.get("answer_spec") or {}
    foundational_papers = answer_spec.get("foundational_papers") or []
    if foundational_papers and not is_fast:
        for fp in foundational_papers[:2]:
            title = fp.get("title", "")
            if not title:
                continue
            try:
                oa_results = await search_openalex_by_title_async(title, 3)
                arxiv_results = await search_arxiv_by_title_async(title, 3)
                for p in oa_results + arxiv_results:
                    p["_foundational_candidate"] = True
                    p["_foundational_source"] = "explicit"
                    p["_source_term"] = title
                all_rows = merge_duplicate_papers(all_rows + oa_results + arxiv_results)
            except Exception:
                pass

    _verify_primary_sources(all_rows, plan)

    query_embedding = (
        await asyncio.to_thread(
            embed_texts,
            [state["query"]],
        )
    )[0]

    await _embed_candidates(all_rows, query_embedding)

    candidates = all_rows

    needs = derive_research_needs(
        state.get("query", ""),
        state.get("query_understanding") or {},
        state.get("report_plan") or {},
    )

    coverage = assess_coverage(needs, candidates)

    gaps = uncovered_needs(
        coverage,
        max_items=2,
    )

    if (
        not is_fast
        and gaps
        and metrics.total < maxes["total"]
    ):
        understanding = state.get("query_understanding") or {}

        main_topic = str(understanding.get("main_topic") or "").strip()

        gap_capabilities = sorted(
            all_capabilities
            or {"secondary_research"}
        )

        for gap in gaps[:2]:
            if metrics.total >= maxes["total"]:
                break

            gap = str(gap).strip()

            if not gap:
                continue

            if len(gap.split()) < 4 and main_topic:
                gap_query = f"{main_topic} {gap}"

            else:
                gap_query = gap

            rows = await _fetch_intent(
                {
                    "query": gap_query[:140],
                    "purpose": "requirement",
                    "priority": 2,
                    "source_capabilities": gap_capabilities,
                },
                maxes,
                metrics,
                web_intent,
                min_year=min_year,
                max_year=max_year,
            )

            for paper in rows:
                paper["_followup_for_gap"] = True

            candidates = merge_duplicate_papers(candidates + rows)

        await _embed_candidates(candidates, query_embedding)

        _verify_primary_sources(candidates, plan)

        coverage = assess_coverage(needs, candidates)

    weak = [
        value
        for value in coverage.values()
        if value.get("status") != "covered"
    ]
    if plan.get("use_citation_backtracking") and not is_fast:
        discovered: list[dict] = []
        already_foundational = any(
            p.get("_foundational_candidate") for p in candidates
        )
        if not already_foundational:
            discovered = await _foundational_convergence_budgeted(
                candidates,
                maxes,
                metrics,
            )

        if not discovered and weak:
            discovered = await _citation_backtrack_budgeted(
                sorted(
                    candidates,
                    key=lambda p: p.get("_initial_sim", 0),
                    reverse=True,
                )[:6],
                maxes,
                metrics,
            )

        if discovered:
            candidates = merge_duplicate_papers(candidates + discovered)
            await _embed_candidates(candidates, query_embedding)
            _verify_primary_sources(candidates, plan)

    sim_thresh = (
        BASE_SIM_THRESH_FAST
        if is_fast
        else BASE_SIM_THRESH_RESEARCH
    )

    RELAXED_SIM_FLOOR = sim_thresh * 0.75

    filtered = [
        paper
        for paper in sorted(
            candidates,
            key=lambda x: x.get("_initial_sim", 0),
            reverse=True,
        )
        if (paper.get("_initial_sim") or 0) >= sim_thresh
        or paper.get("_foundational_candidate")
        or paper.get("_primary_candidate")
    ]

    if len(filtered) < max(6, target_k):
        relaxed = [
            paper
            for paper in sorted(
                candidates,
                key=lambda x: x.get("_initial_sim", 0),
                reverse=True,
            )
            if (paper.get("_initial_sim") or 0) >= RELAXED_SIM_FLOOR
            or paper.get("_foundational_candidate")
            or paper.get("_primary_candidate")
        ]

        if relaxed:
            filtered = relaxed[: max(16, target_k * 2)]

    combined = filtered[:MAX_TOTAL_CANDIDATES]

    coverage = assess_coverage(needs, combined)

    found_primary = sum(
        1
        for paper in combined
        if paper.get("_primary_candidate")
    )

    found_foundational = sum(
        1
        for paper in combined
        if paper.get("_foundational_candidate")
    )

    covered_count = sum(
        1
        for value in coverage.values()
        if value.get("status") == "covered"
    )

    print(
        "[search] budget:\n"
        f"total={metrics.total}/{maxes['total']}\n"
        f"openalex={metrics.openalex}/{maxes['openalex']}\n"
        f"arxiv={metrics.arxiv}/{maxes['arxiv']}\n"
        f"web={metrics.web}/{maxes['web']}\n"
        f"primary={found_primary}\n"
        f"foundational={found_foundational}\n"
        f"coverage={covered_count}/{len(coverage)}"
    )

    if (
        settings.SEMANTIC_CACHE_ENABLED
        and evidence_mode != "uploaded"
        and combined
    ):
        await asyncio.to_thread(
            semantic_cache.set_search_cache,
            state["query"],
            scope,
            combined,
            query_embedding,
        )

    return {
        "raw_search_results": combined,
        "search_attempts": state.get("search_attempts", 0) + 1,
        "needs_retry": False,
        "query_embedding": query_embedding,
        "search_cache_hit": False,
        "term_coverage": coverage,
    }


async def search_node(state: AgentState) -> AgentState:
    if state.get("evidence_mode") == "uploaded":
        return {
            "raw_search_results": [],
            "needs_retry": False,
            "search_cache_hit": False,
            "term_coverage": {},
        }

    mode = state.get("response_mode", "normal")
    evidence_mode = state.get("evidence_mode", "literature")

    query = state.get("query", "")

    scope = f"search:{mode}:{evidence_mode}"

    if settings.SEMANTIC_CACHE_ENABLED and evidence_mode != "uploaded":
        cached = await asyncio.to_thread(
            semantic_cache.get_search_cache,
            query,
            scope,
        )

        if cached:
            print(
                f"[search] semantic cache hit "
                f"similarity={cached.get('_cache_similarity', 0):.3f}"
            )

            return await _materialize_cached_search(state, cached)

    dedup_key = semantic_cache.make_scope_key(query, scope)

    if settings.REQUEST_DEDUP_ENABLED:
        return await request_dedup.execute_once_async(
            dedup_key,
            lambda: _search_core_async(state, scope),
        )

    return await _search_core_async(state, scope)