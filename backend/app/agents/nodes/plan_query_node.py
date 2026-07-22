import json
from langchain_core.messages import SystemMessage, HumanMessage
from app.agents.state import AgentState
from app.agents.schemas import QueryUnderstanding, QueryPlan
from app.services.llm_client import get_llm

def plan_query_node(state: AgentState) -> AgentState:
    query = state["query"]
    history = state.get("conversation_history", [])
    mode = state.get("response_mode", "normal")
    llm = get_llm(temperature=0)

    if history:
        rewrite_prompt = f"""You are an expert search strategist. The user is asking a follow-up question in an ongoing research conversation.
Conversation History:
{json.dumps(history[-4:])}

Current Follow-up Question: {query}

Rewrite the follow-up question into a standalone, comprehensive search query that captures the full context. 
If the follow-up is clearly about a specific paper or topic from the history, include the paper title or topic name.
If the follow-up is a general conversational query (e.g. "summarize that", "what did you say?"), extract the core research topic from the history.
Return ONLY the rewritten search query, nothing else."""
        try:
            rewritten = llm.invoke([
                SystemMessage(content="You rewrite follow-up questions into standalone search queries."), 
                HumanMessage(content=rewrite_prompt)
            ], config={"timeout": 10}).content.strip()
            if rewritten and len(rewritten) < 200:
                query = rewritten
                print(f"[plan_query] Rewritten follow-up query: {query}")
        except Exception as e:
            print(f"[plan_query] Query rewrite failed: {e}")

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

    all_queries = [query]
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
        "search_terms": unique_queries, 
    }
