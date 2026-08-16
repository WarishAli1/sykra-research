import re
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, Field
from typing import Literal
from app.agents.state import AgentState
from app.agents.research_engine import derive_research_needs
from app.services.llm_client import get_llm
from app.agents.report_modules import _is_technical_derivation

class QueryAnalysis(BaseModel):
    main_topic: str = Field(default="")
    subtopics: list[str] = Field(default_factory=list)
    objectives: list[str] = Field(default_factory=list)
    methods_techniques: list[str] = Field(default_factory=list)
    application_domain: str = Field(default="")
    acronyms: dict[str, str] = Field(default_factory=dict)
    entities: list[str] = Field(default_factory=list)
    academic_terminology: list[str] = Field(default_factory=list)
    source_intent: Literal[
        "academic", 
        "clinical_medical", 
        "technical_standards", 
        "financial_economic", 
        "legal_policy", 
        "industry_market"
    ] = Field(default="academic", description="The primary type of authoritative source needed beyond academic papers.")
    rewritten_queries: list[str] = Field(default_factory=list)
    expanded_queries: list[str] = Field(default_factory=list)
    method_queries: list[str] = Field(default_factory=list)
    domain_queries: list[str] = Field(default_factory=list)
    fallback_queries: list[str] = Field(default_factory=list)


def _to_list(value) -> list[str]:
    if value is None:
        return []

    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []

        if "," in text or ";" in text:
            return [
                p.strip()
                for p in re.split(r"[;,]", text)
                if p.strip()
            ]

        return [text]

    if isinstance(value, dict):
        return [str(v).strip() for v in value.values() if str(v).strip()]

    return [str(value).strip()]


def _clean_query_text(text: str) -> str:
    text = re.sub(r"[^\w\s+#().,-]", " ", text or "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _deterministic_search_queries(query: str) -> list[str]:
    """
    Pure-code fallback query expansion.
    This guarantees multiple search terms even if the LLM fails.
    """
    q = _clean_query_text(query)
    if not q:
        return []

    queries = [q]

    first_sentence = q.split(".")[0].strip()

    domain = ""
    domain_match = re.search(r"\bfor\s+(.+)$", first_sentence, flags=re.IGNORECASE)
    if domain_match:
        domain = domain_match.group(1).strip(" .")

    core = re.split(
        r"\b(?:discuss|include|focus|covering|compare|comparison|explain|describe)\b",
        first_sentence.lower(),
        maxsplit=1,
    )[0]

    core = core.strip(" .,")

    items = re.split(
        r"\s*(?:,| and | vs\.? | versus | & )\s*",
        core,
    )

    cleaned_items = []
    for item in items:
        item = item.strip()
        item = re.sub(r"^(compare|comparison of)\s+", "", item)
        item = item.strip(" .")

        if len(item) >= 4 and len(item) <= 90:
            cleaned_items.append(item)

    for item in cleaned_items[:4]:
        if domain:
            queries.append(f"{item} {domain}")
        else:
            queries.append(item)

    if len(cleaned_items) >= 2:
        comparison_query = " vs ".join(cleaned_items[:3])
        if domain:
            comparison_query = f"{comparison_query} {domain}"
        queries.append(comparison_query)

    seen = set()
    unique = []

    for item in queries:
        item = item.strip()
        key = item.lower()

        if not item:
            continue

        if key in seen:
            continue

        seen.add(key)
        unique.append(item)

    return unique[:6]


def _normalize_query_analysis(data, query: str) -> QueryAnalysis:
    """
    Normalizes raw LLM JSON into QueryAnalysis.

    This fixes cases where small models return strings instead of arrays:
        "subtopics": "A, B, C"
    becomes:
        ["A", "B", "C"]
    """
    if not isinstance(data, dict):
        data = {}

    normalized = {}

    for name in QueryAnalysis.model_fields:
        value = data.get(name)

        if name == "main_topic":
            if isinstance(value, list):
                value = value[0] if value else ""
            normalized[name] = str(value or query).strip()

        elif name == "application_domain":
            if isinstance(value, list):
                value = value[0] if value else ""
            normalized[name] = str(value or "").strip()

        elif name == "acronyms":
            normalized[name] = value if isinstance(value, dict) else {}

        elif name == "source_intent":
            valid_intents = {
                "academic",
                "clinical_medical",
                "technical_standards",
                "financial_economic",
                "legal_policy",
                "industry_market",
            }

            if isinstance(value, list):
                value = value[0] if value else None

            value = str(value or "").strip()

            normalized[name] = (
                value if value in valid_intents else "academic"
            )

        else:
            normalized[name] = _to_list(value)

    deterministic = _deterministic_search_queries(query)

    if not normalized.get("rewritten_queries"):
        normalized["rewritten_queries"] = [query]

    if not normalized.get("expanded_queries"):
        normalized["expanded_queries"] = deterministic[:3]

    if not normalized.get("method_queries"):
        normalized["method_queries"] = deterministic[1:3]

    if not normalized.get("domain_queries"):
        normalized["domain_queries"] = deterministic[2:4]

    if not normalized.get("fallback_queries"):
        normalized["fallback_queries"] = deterministic[:2]

    if not normalized.get("entities"):
        normalized["entities"] = deterministic[:4]

    if not normalized.get("methods_techniques"):
        normalized["methods_techniques"] = deterministic[:4]

    return QueryAnalysis(**normalized)


def plan_query_node(state: AgentState) -> AgentState:
    query = state["query"]
    history = state.get("conversation_history", [])
    mode = state.get("response_mode", "normal")

    is_normal = mode == "normal"
    is_derivation = _is_technical_derivation(query)

    llm_fast = get_llm(temperature=0, task="fast")

    refined_query = None

    if history:
        rewrite_prompt = f"""You are an expert search strategist.
Rewrite this follow-up question into a standalone search query.

Conversation History:
{history[-4:]}

Current Follow-up Question:
{query}

Return ONLY the rewritten search query.
"""
        try:
            rewritten = llm_fast.invoke(
                [
                    SystemMessage(
                        content="You rewrite follow-up questions into standalone search queries."
                    ),
                    HumanMessage(content=rewrite_prompt),
                ],
                config={"timeout": 3 if is_normal else 6},
            ).content.strip()

            if rewritten and len(rewritten) < 200:
                refined_query = rewritten
                query = rewritten
                print(f"[plan_query] Rewritten follow-up query: {query}")

        except Exception as e:
            print(f"[plan_query] Query rewrite failed: {type(e).__name__}: {e}")

    target_count = 4 if (is_normal or is_derivation) else 8

    system_prompt = (
        "You are an expert academic research assistant and search strategist. "
        "Analyze the user's research query and generate search queries. "
        "Return ONLY a valid JSON object. "
        "No markdown. No code fences. No explanations."
    )

    human_prompt = f"""User Query:
{query}

Return a JSON object with these fields:

main_topic: string
subtopics: array of strings
objectives: array of strings
methods_techniques: array of strings
application_domain: string
acronyms: object
entities: array of strings
academic_terminology: array of strings
source_intent: string
rewritten_queries: array of strings
expanded_queries: array of strings
method_queries: array of strings
domain_queries: array of strings
fallback_queries: array of strings
source_intent MUST be exactly one of:
"academic",
"clinical_medical",
"technical_standards",
"financial_economic",
"legal_policy",
"industry_market"

Rules:
Target around {target_count} total search queries.
Every list field MUST be a JSON array.
If there is only one item, still use an array like ["item"].
Keep queries concise and high precision.
Do not return the original query inside generated query lists.
"""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt),
    ]

    try:
        raw = llm_fast.invoke_json_mode(
            messages,
            config={"timeout": 5 if is_normal else 8},
        )

        analysis = _normalize_query_analysis(raw, query)

    except Exception as e:
        print(f"[plan_query] JSON analysis failed, using deterministic fallback: {type(e).__name__}: {e}")
        analysis = _normalize_query_analysis({}, query)

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

    needs = derive_research_needs(query, understanding, {"information_needs": analysis.objectives})
    explicit_tasks = [n.text for n in needs if n.kind in ("explicit_task", "query_clause")][:10]
    implicit_subtopics = [n.text for n in needs if n.kind in ("subtopic", "mechanism", "entity")][:12]

    plan["information_needs"] = [n.text for n in needs[:20]]
    understanding["explicit_tasks"] = explicit_tasks
    understanding["implicit_subtopics"] = implicit_subtopics

    if is_normal:
        all_queries = [query]
        all_queries.extend(analysis.rewritten_queries[:1])
        all_queries.extend(analysis.method_queries[:1])
        all_queries.extend(analysis.domain_queries[:1])
        all_queries.extend(analysis.expanded_queries[:1])
    else:
        all_queries = [query]
        all_queries.extend(analysis.rewritten_queries)
        all_queries.extend(analysis.expanded_queries)
        all_queries.extend(analysis.method_queries)
        all_queries.extend(analysis.domain_queries)
        all_queries.extend(analysis.fallback_queries)

    unique_queries = list(
        dict.fromkeys(
            q.strip()
            for q in all_queries
            if q and q.strip()
        )
    )

    unique_queries = unique_queries[:5 if (is_normal or is_derivation) else 9]

    if not is_normal:
        unique_queries.extend(plan["information_needs"][:4])
        unique_queries = list(dict.fromkeys([q.strip() for q in unique_queries if q and q.strip()]))
        unique_queries = unique_queries[:12]

    return {
        "refined_query": refined_query,
        "query_understanding": understanding,
        "query_plan": plan,
        "search_queries": unique_queries,
        "search_terms": unique_queries,
    }