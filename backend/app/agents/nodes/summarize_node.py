import json
from difflib import SequenceMatcher

from langchain_core.messages import SystemMessage, HumanMessage
from app.agents.state import AgentState
from app.agents.schemas import BatchPaperSummaries, ClusteredFinalAnswer, ClusterSection
from app.services.llm_client import get_llm
from app.services.clustering import cluster_papers
from app.utils.text_cleaning import sanitize_abstract

TYPE_ORDER = {"foundational": 0, "survey": 1, "application": 2, "optimization": 3, "evaluation": 4}


def order_for_synthesis(papers: list[dict]) -> list[dict]:
    return sorted(papers, key=lambda p: TYPE_ORDER.get(p.get("paper_type", "application"), 5))


def _flag_ungrounded_overreach(answer: str, uncovered_terms: list[str]) -> list[str]:
    violations = []
    for term in uncovered_terms:
        term_lower = term.lower()
        if term_lower in answer.lower():
            sentences = [s for s in answer.split(".") if term_lower in s.lower()]
            for s in sentences:
                if len(s.split()) > 15:
                    violations.append(term)
    return violations


def _is_near_duplicate(a: str, b: str, threshold: float = 0.6) -> bool:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio() > threshold


def _stitch_answer(clustered_result: ClusteredFinalAnswer) -> str:
    parts = [clustered_result.overview, ""]
    for section in clustered_result.sections:
        parts.append(f"**{section.theme}**\n{section.content}")
    return "\n\n".join(parts)


def summarize_node(state: AgentState) -> AgentState:
    llm = get_llm(temperature=0)
    papers = state["ranked_papers"]

    if not papers:
        return {
            **state,
            "final_answer": "No papers were available to synthesize an answer from.",
            "coverage_gaps": state.get("search_terms", []),
        }

    paper_parts = []
    for i, p in enumerate(papers):
        abstract = p.get("text", sanitize_abstract(p.get("summary", "")))
        if len(abstract) < 20 or "\x02" in abstract or "\x01" in abstract:
            abstract = f"[Abstract stripped for compatibility. Paper: {p['title']}]"
        paper_parts.append(f"[paper_id={i}] Title: {p['title']}\nAbstract: {abstract[:1500]}")
    paper_block = "\n\n".join(paper_parts)

    batch_messages = [
        SystemMessage(content="You must summarize each paper using the BatchPaperSummaries function. Return a valid function call with no additional text before or after."),
        HumanMessage(content=f"Query: {state['query']}\n\n{paper_block}"),
    ]
    summaries = {}
    try:
        result: BatchPaperSummaries = llm.with_structured_output(BatchPaperSummaries).invoke(
            batch_messages, config={"timeout": 20}
        )
        summaries = {s.paper_id: s.model_dump() for s in result.summaries}
        print("[summarize] path=primary_structured")
    except Exception:
        try:
            raw = llm.invoke(batch_messages, config={"timeout": 20})
            clean = raw.content if hasattr(raw, "content") else str(raw)
            if "```" in clean:
                clean = clean.split("```")[1]
                if clean.startswith("json"):
                    clean = clean[4:]
            data = json.loads(clean)
            result = BatchPaperSummaries(**data)
            summaries = {s.paper_id: s.model_dump() for s in result.summaries}
            print("[summarize] path=batch_json_fallback")
        except Exception:
            print("[summarize] path=batch_fallback_failed")
            summaries = {}

    if not summaries:
        summaries = {
            str(i): {
                "key_contribution": f"Paper '{p['title']}' – no abstract available.",
                "methodology": "",
                "findings": "",
                "relevance_to_query": p.get("final_score", 0),
            }
            for i, p in enumerate(papers)
        }

    for i in range(len(papers)):
        summaries.setdefault(str(i), {
            "paper_id": str(i), "key_contribution": "not summarized",
            "methodology": "", "findings": "", "relevance_to_query": ""
        })

    term_coverage = state.get("term_coverage", {})
    covered_terms = [t for t, ok in term_coverage.items() if ok]
    uncovered_terms = [t for t, ok in term_coverage.items() if not ok]

    query_parts = state.get("search_terms", [state["query"]])
    parts_str = "; ".join(f'"{t}"' for t in query_parts)

    # --- Clustering ---
    try:
        clusters = cluster_papers(papers, max_clusters=4)
    except Exception as e:
        print(f"[clustering] failed ({type(e).__name__}: {e}), falling back to flat list")
        clusters = [[p] for p in papers]

    cluster_blocks = []
    for idx, cluster in enumerate(clusters):
        paper_lines = "\n".join(
            f"  [paper_id={papers.index(p)}] {p['title']}: {summaries.get(str(papers.index(p)), {}).get('key_contribution', '')}"
            for p in cluster
        )
        cluster_blocks.append(f"Cluster {idx} ({len(cluster)} paper(s)):\n{paper_lines}")
    cluster_context = "\n\n".join(cluster_blocks)

    n_clusters = len(clusters)
    final_prompt = f"""You are a research assistant. Answer the user's query using ONLY the paper summaries below.

CRITICAL RULES FOR UPLOADED DOCUMENTS:
- If the user uploaded a document and the query is about it, answer STRICTLY from the uploaded document. Do not use external knowledge.
- You MUST include page numbers in your citations when referencing the uploaded document (e.g., "According to the document [Page 3]...").
- If the uploaded document does not contain the answer, state that clearly.

The following concepts HAVE supporting evidence in the retrieved papers: {covered_terms or "none"}
The following concepts DO NOT have supporting evidence in the retrieved papers: {uncovered_terms or "none"}

Write a clear, concept-first explanation — not a paper-by-paper inventory.
Organise your answer around the main themes, using the pre-grouped clusters as a guide.
For each concept that is **not** covered, simply state: "The retrieved papers do not contain information about <concept>."
Do not include any inline citation markers (like [paper_id]). The full list of sources will be provided separately.

The papers have been pre-grouped into {n_clusters} thematic clusters below.
Produce exactly {n_clusters} sections in your response — one per cluster, no more, no fewer.
Each section should be a cohesive paragraph of 3-5 sentences, not a list of paper summaries.

This query has multiple parts: {parts_str}

User query: {state['query']}

Pre-grouped paper clusters:
{cluster_context}

Produce a ClusteredFinalAnswer JSON object with exactly {n_clusters} sections,
one per cluster, with fields: sections, overview, confidence, coverage_gaps.
For coverage_gaps, use exactly this list: {uncovered_terms}
"""
    final_messages = [
        SystemMessage(content=f"Respond with ONLY a function call to ClusteredFinalAnswer with exactly {n_clusters} sections. No text before or after."),
        HumanMessage(content=final_prompt),
    ]

    try:
        final: ClusteredFinalAnswer = llm.with_structured_output(ClusteredFinalAnswer).invoke(
            final_messages, config={"timeout": 20}
        )
        print("[summarize] path=final_structured")
    except Exception:
        try:
            fallback_ans = llm.invoke(
                f"Based on these paper summaries, answer the user's query. Be honest about gaps.\n\nSummaries:\n{cluster_context}\n\nQuery: {state['query']}\n\nAnswer:",
                config={"timeout": 20}
            )
            answer_text = fallback_ans.content if hasattr(fallback_ans, "content") else str(fallback_ans)
            final = ClusteredFinalAnswer(
                sections=[ClusterSection(theme="All papers", content=answer_text, paper_ids=[str(i) for i in range(len(papers))])],
                overview="",
                confidence=0.3,
                coverage_gaps=uncovered_terms,
            )
            print("[summarize] path=final_plain_fallback")
        except Exception:
            final = ClusteredFinalAnswer(
                sections=[],
                overview="I could not synthesize the answer due to a processing error.",
                confidence=0.0,
                coverage_gaps=uncovered_terms,
            )
            print("[summarize] path=final_fallback_failed")

    final.coverage_gaps = uncovered_terms

    # --- Validate and repair sections ---
    valid_ids = {str(i) for i in range(len(papers))}
    for section in final.sections:
        section.paper_ids = [pid for pid in section.paper_ids if pid in valid_ids]

    if final.sections and len(final.sections) != n_clusters:
        print(f"[summarize] WARN: expected {n_clusters} sections, got {len(final.sections)}")
        if len(final.sections) < n_clusters:
            covered_ids = {pid for s in final.sections for pid in s.paper_ids}
            for idx, cluster in enumerate(clusters):
                cluster_pids = [str(papers.index(p)) for p in cluster]
                if not any(pid in covered_ids for pid in cluster_pids):
                    final.sections.append(ClusterSection(
                        theme=f"Additional papers (cluster {idx})",
                        content="These papers were retrieved but not covered in the synthesized answer.",
                        paper_ids=cluster_pids,
                    ))
                    if len(final.sections) >= n_clusters:
                        break
        else:
            final.sections = final.sections[:n_clusters]

    # --- Dedup check: drop overview if it near-duplicates first section ---
    if final.sections and _is_near_duplicate(final.overview, final.sections[0].content):
        print("[WARN] overview duplicates first section content, dropping overview")
        final.overview = ""

    answer_text = _stitch_answer(final)

    overreach = _flag_ungrounded_overreach(answer_text, uncovered_terms)
    if overreach:
        print(f"[WARN] Model may have overreached on uncovered terms: {overreach}")
        final.confidence = min(final.confidence, 0.3)

    return {
        **state,
        "summaries": summaries,
        "final_answer": answer_text,
        "coverage_gaps": final.coverage_gaps,
        "domain_caveat": state.get("domain_caveat"),
    }
