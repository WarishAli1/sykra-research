from app.agents.state import AgentState
from app.agents.schemas import BatchPaperScores
from app.services.llm_client import get_llm
from app.services.embeddings import embed_texts, similarity
from app.config import settings

PRE_FILTER_N = 10


def add_embedding_scores(query: str, papers: list[dict]) -> list[dict]:
    query_vec = embed_texts([query])[0]
    abstracts = [p.get("summary", "")[:500] for p in papers]
    abstract_vecs = embed_texts(abstracts)
    for p, vec in zip(papers, abstract_vecs):
        p["embedding_score"] = round(similarity(query_vec, vec), 3)
    return papers


def prefilter_candidates(papers: list[dict], n: int) -> list[dict]:
    seminal = [p for p in papers if p.get("source") == "seminal_lookup"]
    others = sorted(
        (p for p in papers if p.get("source") != "seminal_lookup"),
        key=lambda p: p.get("embedding_score", 0),
        reverse=True,
    )
    return seminal + others[: max(0, n - len(seminal))]


def select_diverse_topk(papers: list[dict], k: int) -> list[dict]:
    ranked = sorted(papers, key=lambda p: p["blended_score"], reverse=True)
    selected, selected_ids = [], set()

    for p in ranked:
        if p["paper_type"] in ("foundational", "survey"):
            selected.append(p)
            selected_ids.add(id(p))
            break

    type_counts = {}
    for p in ranked:
        if len(selected) >= k:
            break
        if id(p) in selected_ids:
            continue
        t = p["paper_type"]
        if type_counts.get(t, 0) >= 2:
            continue
        selected.append(p)
        selected_ids.add(id(p))
        type_counts[t] = type_counts.get(t, 0) + 1

    for p in ranked:
        if len(selected) >= k:
            break
        if id(p) not in selected_ids:
            selected.append(p)
            selected_ids.add(id(p))

    return selected[:k]


def rank_node(state: AgentState) -> AgentState:
    papers = state["raw_search_results"]

    if not papers:
        return {**state, "ranked_papers": [], "needs_retry": True}

    papers = add_embedding_scores(state["query"], papers)
    papers = prefilter_candidates(papers, PRE_FILTER_N)

    is_def = state.get("is_definitional", False)
    weight = 0.7 if is_def else 0.4

    llm = get_llm(temperature=0)
    batch_llm = llm.with_structured_output(BatchPaperScores)

    paper_block = "\n\n".join(
        f"[{i}] Title: {p['title']}\n"
        f"Citations: {p.get('citation_count', 'unknown')}\n"
        f"Abstract: {p.get('summary', '')[:600]}"
        for i, p in enumerate(papers)
    )

    prompt = f"""Score EACH paper below against the query, RELATIVE TO EACH OTHER.
Spread your scores meaningfully across the full 0-1 range — do not assign the same or near-identical
scores to papers unless they are genuinely equally relevant. You are comparing {len(papers)} papers
at once specifically so you can differentiate between them.

Query: {state['query']}

Papers:
{paper_block}

For each paper (referenced by its index above), return relevance_to_query, foundational_importance,
paper_type, and a 1-sentence justification citing a specific detail from its abstract.
"""

    try:
        result: BatchPaperScores = batch_llm.invoke(prompt)
        score_map = {s.paper_index: s for s in result.scores}
    except Exception:
        score_map = {}

    for i, paper in enumerate(papers):
        s = score_map.get(i)
        if s:
            paper["relevance_to_query"] = s.relevance_to_query
            paper["foundational_importance"] = s.foundational_importance
            paper["paper_type"] = s.paper_type
            paper["ranking_reasoning"] = s.justification
            paper["relevance_score"] = round(
                weight * s.foundational_importance + (1 - weight) * s.relevance_to_query, 3
            )
        else:
            paper["relevance_to_query"] = 0.0
            paper["foundational_importance"] = 0.0
            paper["paper_type"] = "application"
            paper["ranking_reasoning"] = "scoring failed"
            paper["relevance_score"] = 0.0

        paper["blended_score"] = round(
            0.6 * paper["relevance_score"] + 0.4 * paper.get("embedding_score", 0), 3
        )

    seen_titles = set()
    deduped = []
    for p in sorted(papers, key=lambda p: p["blended_score"], reverse=True):
        norm_title = p["title"].strip().lower()
        if norm_title in seen_titles:
            continue
        seen_titles.add(norm_title)
        deduped.append(p)

    top_k = select_diverse_topk(deduped, settings.TOP_K_PAPERS)

    max_score = max((p.get("blended_score", 0) for p in top_k), default=0)
    needs_retry = (
        max_score < 0.3
        and state.get("search_attempts", 0) < state.get("max_search_attempts", 2)
    )

    return {**state, "ranked_papers": top_k, "needs_retry": needs_retry}
