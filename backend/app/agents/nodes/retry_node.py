import json

from langchain_core.messages import SystemMessage, HumanMessage
from app.agents.state import AgentState
from app.services.llm_client import get_llm


def retry_node(state: AgentState) -> AgentState:
    llm = get_llm(temperature=0.4, task="light")

    prompt = f"""Original query: "{state['query']}" returned few or no relevant papers.
Domain (if any): {state.get('domain_full', 'none')}
Mandatory keywords that must appear: {state.get('mandatory_domain_keywords', [])}

Generate 3-4 alternative search phrases that would find more papers on this topic.
- Each phrase MUST include the domain concept (e.g., for NLP, include 'language' or 'text').
- Use synonyms, broader terms, or related tasks.
- Output ONLY a JSON list of strings.
Example: ["prompt-based few-shot learning natural language processing", "in-context learning text classification", "few-shot NLP transfer learning"]
JSON:
"""
    raw = llm.invoke(prompt).content.strip()
    try:
        new_terms = json.loads(raw)
        if not isinstance(new_terms, list):
            new_terms = [raw]
    except Exception:
        new_terms = [raw]

    return {
        **state,
        "search_terms": new_terms,
        "refined_query": None,
        "needs_retry": False,
    }