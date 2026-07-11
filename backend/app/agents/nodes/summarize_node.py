import json

from langchain_core.messages import SystemMessage, HumanMessage
from app.agents.state import AgentState
from app.agents.schemas import BatchPaperSummaries, FinalAnswer
from app.services.llm_client import get_llm
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


def _count_citations(answer: str) -> int:
    import re
    return len(set(re.findall(r'\[(\d+)\]', answer)))


def summarize_node(state: AgentState) -> AgentState:
    llm = get_llm(temperature=0)
    papers = state["ranked_papers"]

    paper_parts = []
    for i, p in enumerate(papers):
        abstract = p.get('text', sanitize_abstract(p.get('summary', '')))
        if len(abstract) < 20 or '\x02' in abstract or '\x01' in abstract:
            abstract = f"[Abstract stripped for compatibility. Paper: {p['title']}]"
        paper_parts.append(f"[paper_id={i}] Title: {p['title']}\nAbstract: {abstract[:2500]}")
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

    ordered_papers = order_for_synthesis(papers)
    paper_context = "\n\n".join(
        f"[paper_id={papers.index(p)}] ({p.get('paper_type', 'application').upper()}) {p['title']}: "
        f"{summaries.get(str(papers.index(p)), {}).get('key_contribution', '')}"
        for p in ordered_papers
    )

    term_coverage = state.get("term_coverage", {})
    covered_terms = [t for t, ok in term_coverage.items() if ok]
    uncovered_terms = [t for t, ok in term_coverage.items() if not ok]

    query_parts = state.get("search_terms", [state["query"]])
    parts_str = "; ".join(f'"{t}"' for t in query_parts)

    final_prompt = f"""You are a research assistant. Answer the user's query using ONLY the paper summaries below.

The following concepts HAVE supporting evidence in the retrieved papers: {covered_terms or "none"}
The following concepts DO NOT have supporting evidence in the retrieved papers: {uncovered_terms or "none"}

MANDATORY CITATION RULE: Every substantive claim in your answer MUST be immediately
followed by its source marker in the form [paper_id], e.g. "CNNs use convolutional
layers to extract spatial features [2]." Do not write any factual claim without a
[paper_id] marker attached. If you cannot attach a marker to a claim, do not include
that claim.

Use ALL papers that are genuinely relevant — with {len(papers)} papers provided, a
thorough answer should reference most of them, not just 1-2. A short, generic paragraph
that does not engage with the specific findings of multiple papers is not acceptable.

This query has multiple parts: {parts_str}
Address each part as a distinct section or clearly transitioned paragraph, using
specific findings (not generic restatements) from the papers that support that
specific part. Do not compress multiple sub-questions into a single vague paragraph —
each part deserves its own grounded, detailed treatment given {len(papers)} source
papers were retrieved specifically to cover this query.

Rules:
- Only write substantive claims about concepts listed as HAVING evidence.
- For each concept listed as NOT having evidence, write exactly this sentence and nothing more
  about that concept: "The retrieved papers do not contain information about {{concept}}."
  Do not add explanation, inference, or comparison involving that concept afterward.
- If this query touches health, legal, financial, or safety-critical topics, be extra conservative:
  only state claims with direct, explicit support in the summaries below.

User query: {state['query']}

Paper summaries:
{paper_context}

Produce a FinalAnswer JSON object with fields: answer, confidence, papers_used, coverage_gaps.
For coverage_gaps, use exactly this list: {uncovered_terms}
"""
    final_messages = [
        SystemMessage(content="You must synthesize an answer using the FinalAnswer function. Return a valid function call with no additional text."),
        HumanMessage(content=final_prompt),
    ]
    try:
        final: FinalAnswer = llm.with_structured_output(FinalAnswer).invoke(
            final_messages, config={"timeout": 20}
        )
        print("[summarize] path=final_structured")
    except Exception:
        try:
            fallback_ans = llm.invoke(
                f"Based on these paper summaries, answer the user's query. Be honest about gaps.\n\nSummaries:\n{paper_context}\n\nQuery: {state['query']}\n\nAnswer:",
                config={"timeout": 20}
            )
            answer_text = fallback_ans.content if hasattr(fallback_ans, "content") else str(fallback_ans)
            final = FinalAnswer(
                answer=answer_text,
                confidence=0.3,
                papers_used=[str(i) for i in range(len(papers))],
                coverage_gaps=uncovered_terms,
            )
            print("[summarize] path=final_plain_fallback")
        except Exception:
            final = FinalAnswer(
                answer="I could not synthesize the answer due to a processing error.",
                confidence=0.0,
                papers_used=[],
                coverage_gaps=uncovered_terms,
            )
            print("[summarize] path=final_fallback_failed")

    final.coverage_gaps = uncovered_terms

    overreach = _flag_ungrounded_overreach(final.answer, uncovered_terms)
    if overreach:
        print(f"[WARN] Model may have overreached on uncovered terms: {overreach}")
        final.confidence = min(final.confidence, 0.3)

    unique_cited = len(set(final.papers_used or []))
    min_expected = max(3, len(papers) // 2)
    if unique_cited < min_expected and len(papers) >= 3:
        print(f"[summarize] verification: only {unique_cited}/{len(papers)} papers cited, regenerating")
        try:
            verify_prompt = final_prompt + f"""

Your previous draft only cited {unique_cited} out of {len(papers)} papers.
This is not acceptable. You MUST rewrite the answer to substantively engage with
and cite at least {min_expected} different papers using [paper_id] markers.
Every factual claim must have a [paper_id] immediately after it.
"""
            verify_messages = [
                SystemMessage(content="You must synthesize an answer using the FinalAnswer function. Return a valid function call with no additional text."),
                HumanMessage(content=verify_prompt),
            ]
            verified: FinalAnswer = llm.with_structured_output(FinalAnswer).invoke(
                verify_messages, config={"timeout": 20}
            )
            verified.coverage_gaps = uncovered_terms
            verified_unique = len(set(verified.papers_used or []))
            if verified_unique > unique_cited:
                print(f"[summarize] verification improved: {verified_unique}/{len(papers)} papers cited")
                final = verified
            else:
                print(f"[summarize] verification did not improve, keeping original")
        except Exception:
            print("[summarize] verification failed, keeping original")

    return {**state, "summaries": summaries, "final_answer": final.answer, "coverage_gaps": final.coverage_gaps, "domain_caveat": final.domain_caveat}
