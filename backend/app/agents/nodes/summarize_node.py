from app.agents.state import AgentState
from app.agents.schemas import PaperSummary, FinalAnswer
from app.services.llm_client import get_llm

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
    llm = get_llm(temperature=0.2)
    summary_llm = llm.with_structured_output(PaperSummary)

    summaries = {}
    for i, paper in enumerate(state["ranked_papers"]):
        text_excerpt = paper.get("text", paper.get("summary", ""))[:4000]
        prompt = f"""Query context: {state['query']}

Paper title: {paper['title']}
Paper content excerpt:
{text_excerpt}

Summarize this paper's contribution, methodology, and findings, and explain its relevance to the query.
Use paper_id="{i}".
"""
        try:
            summary: PaperSummary = summary_llm.invoke(prompt)
            summaries[str(i)] = summary.model_dump()
        except Exception as e:
            summaries[str(i)] = {
                "paper_id": str(i),
                "key_contribution": "Could not summarize (LLM error)",
                "methodology": "",
                "findings": "",
                "relevance_to_query": "",
            }

    ordered_papers = order_for_synthesis(state["ranked_papers"])

    paper_context = "\n\n".join(
        f"[{p.get('paper_type', 'application').upper()}] {p['title']}: "
        f"Contribution: {summaries.get(str(state['ranked_papers'].index(p)), {}).get('key_contribution', '')}\n"
        f"Methodology: {summaries.get(str(state['ranked_papers'].index(p)), {}).get('methodology', '')}\n"
        f"Findings: {summaries.get(str(state['ranked_papers'].index(p)), {}).get('findings', '')}"
        for p in ordered_papers
    )

    final_llm = llm.with_structured_output(FinalAnswer)

    answer_prompt = f"""User query: {state['query']}

Structure your answer in this order, using transitions that make the progression clear:
1. Start with the CORE CONCEPT — define it using the foundational/survey paper(s) first.
2. Then describe how it's been APPLIED or EXTENDED — application/optimization papers.
3. End with how it's EVALUATED or its known LIMITATIONS — evaluation papers.

Do not present these as an unordered list of unrelated findings — each should build on the previous.

Papers (in the order to discuss them):
{paper_context}
"""
    final: FinalAnswer = final_llm.invoke(answer_prompt)

    return {
        **state,
        "summaries": summaries,
        "final_answer": final.answer,
    }
