from langchain_core.messages import SystemMessage, HumanMessage
from app.agents.state import AgentState
from app.agents.schemas import QueryUnderstanding, QueryPlan
from app.services.llm_client import get_llm

def plan_query_node(state: AgentState) -> AgentState:
    query = state["query"]
    mode = state.get("response_mode", "normal")
    llm = get_llm(temperature=0)

    # Step 1: Query Understanding
    under_sys = "You are an expert academic research assistant. Extract the core components of the user's research query to understand the intent."
    under_human = f"User Query: {query}\n\nExtract the understanding."

    try:
        understanding = llm.with_structured_output(QueryUnderstanding).invoke([
            SystemMessage(content=under_sys),
            HumanMessage(content=under_human)
        ], config={"timeout": 15})
    except Exception:
        understanding = QueryUnderstanding(
            main_topic=query, subtopics=[], objectives=[], methods_techniques=[],
            application_domain="", acronyms={}, entities=[], academic_terminology=[]
        )

    # Step 2: Query Plan (Rewriting & Expansion)
    target_count = 6 if mode == "normal" else 12
    plan_sys = "You are an expert academic search strategist. Generate a diverse set of search queries to maximize recall and precision for academic literature."
    plan_human = f"""
    Original Query: {query}
    Understanding: {understanding.model_dump_json()}

    Generate search queries. Target around {target_count} total queries across all categories.
    - Rewritten (2-3): Semantically equivalent queries using formal academic phrasing.
    - Expanded (2-3): Broader parent concepts, narrower specialized concepts, or related research concepts.
    - Method (1-2): Focus on specific algorithms, models, or techniques identified.
    - Domain (1-2): Focus on the application domain or industry.
    - Fallback (1-2): Very broad queries in case the topic is too narrow.

    Do not include the original query in these lists. Ensure queries are concise (2-6 words).
    """

    try:
        plan = llm.with_structured_output(QueryPlan).invoke([
            SystemMessage(content=plan_sys),
            HumanMessage(content=plan_human)
        ], config={"timeout": 15})
    except Exception:
        plan = QueryPlan(
            rewritten_queries=[], expanded_queries=[], method_queries=[],
            domain_queries=[], fallback_queries=[]
        )

    # Flatten and deduplicate queries
    all_queries = [query] # Always include original
    all_queries.extend(plan.rewritten_queries)
    all_queries.extend(plan.expanded_queries)
    all_queries.extend(plan.method_queries)
    all_queries.extend(plan.domain_queries)

    unique_queries = list(dict.fromkeys(q.strip() for q in all_queries if q.strip()))

    return {
        **state,
        "query_understanding": understanding.model_dump(),
        "query_plan": plan.model_dump(),
        "search_queries": unique_queries,
        "search_terms": unique_queries, # Keep for backward compatibility
    }
