import json
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, Field
from app.agents.state import AgentState
from app.agents.schemas import QueryUnderstanding, QueryPlan
from app.services.llm_client import get_llm


class QueryAnalysis(BaseModel):
    """Combined QueryUnderstanding + QueryPlan in a single structured call."""
    main_topic: str = Field(description="The core research topic")
    subtopics: list[str] = Field(default_factory=list, description="Important subtopics or facets")
    objectives: list[str] = Field(default_factory=list, description="Research objectives or goals")
    methods_techniques: list[str] = Field(default_factory=list, description="Methods, algorithms, models, and techniques")
    application_domain: str = Field(default="", description="The specific application domain")
    acronyms: dict[str, str] = Field(default_factory=dict, description="Acronyms and their expanded forms")
    entities: list[str] = Field(default_factory=list, description="Important entities, datasets, or frameworks")
    academic_terminology: list[str] = Field(default_factory=list, description="Academic terminology commonly used in literature for this topic")
    rewritten_queries: list[str] = Field(default_factory=list, description="2-3 semantically equivalent queries using academic phrasing")
    expanded_queries: list[str] = Field(default_factory=list, description="2-3 broader/narrower/related concepts to improve recall")
    method_queries: list[str] = Field(default_factory=list, description="1-2 queries focusing on specific algorithms/techniques")
    domain_queries: list[str] = Field(default_factory=list, description="1-2 queries focusing on the application domain")
    fallback_queries: list[str] = Field(default_factory=list, description="1-2 very broad queries if the topic is too narrow")


def plan_query_node(state: AgentState) -> AgentState:
    query = state["query"]
    history = state.get("conversation_history", [])
    mode = state.get("response_mode", "normal")

    llm_fast = get_llm(temperature=0, task="fast")

    refined_query = None
    if history:
        rewrite_prompt = f"""You are an expert search strategist. The user is asking a follow-up question in an ongoing research conversation.

Conversation History:
{json.dumps(history[-4:])}

Current Follow-up Question: {query}

Rewrite the follow-up question into a standalone, comprehensive search query that captures the full context.
If the follow-up is clearly about a specific paper or topic from the history, include the paper title or topic name.
If the follow-up is a general conversational query, extract the core research topic from the history.
Return ONLY the rewritten search query, nothing else.
"""
        try:
            rewritten = llm_fast.invoke(
                [
                    SystemMessage(content="You rewrite follow-up questions into standalone search queries."),
                    HumanMessage(content=rewrite_prompt),
                ],
                config={"timeout": 8},
            ).content.strip()
            if rewritten and len(rewritten) < 200:
                refined_query = rewritten
                query = rewritten
                print(f"[plan_query] Rewritten follow-up query: {query}")
        except Exception as e:
            print(f"[plan_query] Query rewrite failed: {type(e).__name__}: {e}")


    target_count = 6 if mode == "normal" else 12

    combined_sys = (
        "You are an expert academic research assistant and search strategist. "
        "Analyze the user's research query to understand intent AND generate diverse search queries. "
        "Respond with ONLY a function call to QueryAnalysis."
    )

    combined_human = f"""User Query: {query}

PART 1 — UNDERSTANDING:
Extract the core components: main_topic, subtopics, objectives, methods_techniques,
application_domain, acronyms, entities, academic_terminology.

PART 2 — SEARCH PLAN:
Generate a diverse set of search queries to maximize recall and precision.
Target around {target_count} total queries across all categories:
- rewritten_queries (2-3): Semantically equivalent queries using formal academic phrasing.
- expanded_queries (2-3): Broader parent concepts, narrower specialized concepts, or related research concepts.
- method_queries (1-2): Focus on specific algorithms, models, or techniques identified.
- domain_queries (1-2): Focus on the application domain or industry.
- fallback_queries (1-2): Very broad queries in case the topic is too narrow.

CRITICAL RULE FOR MULTI-ENTITY COMPARISONS:
If the user asks to compare multiple specific entities, generate individual queries for EACH entity combined with the core domain.
Do not include the original query in these lists. Ensure queries are concise.
"""

    try:
        analysis = llm_fast.with_structured_output(QueryAnalysis).invoke(
            [
                SystemMessage(content=combined_sys),
                HumanMessage(content=combined_human),
            ],
            config={"timeout": 12},
        )
        if isinstance(analysis, dict):
            analysis = QueryAnalysis.model_validate(analysis)
    except Exception as e:
        print(f"[plan_query] Combined analysis failed: {type(e).__name__}: {e}")
        analysis = QueryAnalysis(
            main_topic=query,
            subtopics=[],
            objectives=[],
            methods_techniques=[],
            application_domain="",
            acronyms={},
            entities=[],
            academic_terminology=[],
            rewritten_queries=[],
            expanded_queries=[],
            method_queries=[],
            domain_queries=[],
            fallback_queries=[],
        )

    understanding = {
        "main_topic": analysis.main_topic,
        "subtopics": analysis.subtopics,
        "objectives": analysis.objectives,
        "methods_techniques": analysis.methods_techniques,
        "application_domain": analysis.application_domain,
        "acronyms": analysis.acronyms,
        "entities": analysis.entities,
        "academic_terminology": analysis.academic_terminology,
    }

    plan = {
        "rewritten_queries": analysis.rewritten_queries,
        "expanded_queries": analysis.expanded_queries,
        "method_queries": analysis.method_queries,
        "domain_queries": analysis.domain_queries,
        "fallback_queries": analysis.fallback_queries,
    }

    all_queries = [query]
    all_queries.extend(analysis.rewritten_queries)
    all_queries.extend(analysis.expanded_queries)
    all_queries.extend(analysis.method_queries)
    all_queries.extend(analysis.domain_queries)
    all_queries.extend(analysis.fallback_queries)
    unique_queries = list(dict.fromkeys(q.strip() for q in all_queries if q and q.strip()))

    return {
        "refined_query": refined_query,
        "query_understanding": understanding,
        "query_plan": plan,
        "search_queries": unique_queries,
        "search_terms": unique_queries,
    }