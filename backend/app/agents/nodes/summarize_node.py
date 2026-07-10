import json

from langchain_core.messages import SystemMessage, HumanMessage
from app.agents.state import AgentState
from app.agents.schemas import BatchPaperSummaries, FinalAnswer
from app.services.llm_client import get_llm
from app.utils.text_cleaning import sanitize_abstract

TYPE_ORDER = {
    "foundational": 0,
    "survey": 1,
    "application": 2,
    "optimization": 3,
    "evaluation": 4,
}


def order_for_synthesis(papers: list[dict]) -> list[dict]:
    return sorted(papers, key=lambda p: TYPE_ORDER.get(p.get("paper_type", "application"), 5))


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
    try:
        result: BatchPaperSummaries = llm.with_structured_output(BatchPaperSummaries).invoke(
            batch_messages, config={"timeout": 20}
        )
        summaries = {s.paper_id: s.model_dump() for s in result.summaries}
    except Exception:
        try:
            raw = llm.invoke(batch_messages, config={"timeout": 20})
            clean = str(raw)
            if "```" in clean:
                clean = clean.split("```")[1]
                if clean.startswith("json"):
                    clean = clean[4:]
            data = json.loads(clean)
            result = BatchPaperSummaries(**data)
            summaries = {s.paper_id: s.model_dump() for s in result.summaries}
        except Exception:
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
        f"type: {p.get('paper_type', 'application')} | {p['title']}: "
        f"{summaries.get(str(papers.index(p)), {}).get('key_contribution', '')}"
        for p in ordered_papers
    )

    present_terms = {p.get("_source_term") for p in papers if p.get("_source_term")}
    requested_terms = set(state.get("search_terms", []))
    missing_terms = sorted(requested_terms - present_terms)

    final_prompt = f"""
You are a research assistant. Write a detailed answer to the query, synthesizing information from ALL the provided paper summaries.
- Use every paper at least once.
- Compare and contrast findings.
- Explain concepts clearly, as if to a graduate student.
- Cite papers by index ([0], [1], ...).
- If a paper is only slightly related, still mention any useful insight, but note its limited scope.
- Be honest about gaps; list them in coverage_gaps.
- The answer should be at least 3-4 paragraphs.

User query: {state['query']}

Paper summaries:
{paper_context}
"""
    final_messages = [
        SystemMessage(content="You must synthesize an answer using the FinalAnswer function. Return a valid function call with no additional text."),
        HumanMessage(content=final_prompt),
    ]
    try:
        final: FinalAnswer = llm.with_structured_output(FinalAnswer).invoke(
            final_messages, config={"timeout": 20}
        )
    except Exception:
        try:
            fallback_ans = llm.invoke(
                f"Based on these paper summaries, answer the user's query. Be honest about gaps.\n\nSummaries:\n{paper_context}\n\nQuery: {state['query']}\n\nAnswer:",
                config={"timeout": 20}
            )
            final = FinalAnswer(
                answer=str(fallback_ans),
                confidence=0.3,
                papers_used=[str(i) for i in range(len(papers))],
                coverage_gaps=list(requested_terms) or ["Answer generated via fallback; structured output failed."],
            )
        except Exception:
            final = FinalAnswer(
                answer="I could not synthesize the answer due to a processing error.",
                confidence=0.0,
                papers_used=[],
                coverage_gaps=list(requested_terms),
            )

    return {**state, "summaries": summaries, "final_answer": final.answer, "coverage_gaps": final.coverage_gaps}
