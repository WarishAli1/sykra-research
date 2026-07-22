import json
import re
from difflib import SequenceMatcher
from langchain_core.messages import SystemMessage, HumanMessage
from app.agents.state import AgentState
from app.agents.schemas import BatchPaperSummaries, NormalAnswer, ResearchAnswer, PaperSummaryItem
from app.services.llm_client import get_llm
from app.services.reference_builder import (
    build_references, paper_id_to_ref_id_map, rewrite_inline_citations, format_reference_block,
)
from app.utils.text_cleaning import sanitize_abstract

LATEX_INSTRUCTION = """
MATH FORMATTING (use whenever a formula, equation, or mathematical
expression is part of the answer):
- Always express formulas using real LaTeX delimiters, never plain text or
  ASCII approximations.
- Inline math: wrap in single dollar signs, e.g. $d_k$ or $Q, K, V$.
- Display/standalone equations: wrap in double dollar signs on their own line, e.g.
  $$\\text{Attention}(Q,K,V) = \\text{softmax}\\left(\\frac{QK^T}{\\sqrt{d_k}}\\right)V$$
- Do NOT use \\( \\) or \\[ \\] delimiters, and do NOT emit raw HTML/XML tags
  (e.g. <font>, <para>) around equations — dollar-sign delimiters only.
- Every symbol used in a formula (e.g. Q, K, V, d_k) must be briefly defined
  in prose immediately after the equation.
"""


def _evidence_mode_instruction(mode: str) -> str:
    """Step 6: single prompt-level switch instead of forked answer schemas.
    Confidence semantics also shift per mode (Step 8) — this text makes that
    explicit to the LLM rather than relying on a separate confidence field."""
    if mode == "uploaded":
        return """
EVIDENCE MODE: UPLOADED DOCUMENT ONLY
- Answer ONLY using the uploaded document provided in the papers below.
- Never invent information not present in the document.
- If the document lacks evidence for part of the question, say so explicitly.
- Do NOT cite or reference any outside/external papers.
- CONFIDENCE here means: "How well does the uploaded document answer the
  question?" — NOT how strong external scientific evidence is. High = the
  document directly and thoroughly answers it. Low = the document barely
  touches on it or doesn't address it.
"""
    if mode == "blended":
        return """
EVIDENCE MODE: BLENDED (uploaded document + literature)
- Treat the uploaded document as the PRIMARY source.
- Use retrieved literature only for validation, comparison, or background —
  clearly separate literature-derived claims from document-derived claims.
- CONFIDENCE here means how strong the combined available evidence is
  (document + literature), same as standard literature-mode confidence.
"""
    return """
EVIDENCE MODE: LITERATURE
- Use retrieved literature only.
- CONFIDENCE here means how strong the available research evidence is.
"""


def _invoke_structured_with_repair(llm, messages, schema, max_retries=2):
    """Invokes the LLM with structured output, retrying with error feedback if validation fails."""
    for attempt in range(max_retries + 1):
        try:
            result = llm.with_structured_output(schema).invoke(messages, config={"timeout": 90})
            if isinstance(result, dict):
                result = schema.model_validate(result)
            return result
        except Exception as e:
            if attempt == max_retries:
                print(f"[summarize] Structured output failed after {max_retries} retries: {type(e).__name__}: {e}")
                return None

            error_str = str(e)
            if len(error_str) > 1000:
                error_str = error_str[:1000] + "... (truncated)"

            repair_msg = (
                f"Your previous output failed schema validation.\n"
                f"Errors:\n{error_str}\n\n"
                f"CRITICAL: You MUST correct your output to exactly match the required schema. "
                f"Do not omit any required fields, and ensure all fields are of the correct type. "
                f"Return ONLY a valid function call with no additional text."
            )
            messages = messages + [HumanMessage(content=repair_msg)]
            print(f"[summarize] Schema validation failed, retrying ({attempt + 1}/{max_retries})...")


def _classify_evidence_type(paper: dict, query: str, summaries: dict) -> str:
    """Classify paper as direct, supporting, or background evidence."""
    summary = summaries.get(paper.get("_idx", "0"), {})
    relevance = summary.get("relevance_to_query", "").lower()
    contribution = summary.get("key_contribution", "").lower()
    title = paper.get("title", "").lower()

    direct_indicators = ["directly addresses", "explicitly studies", "proposes", "introduces", "framework for"]
    if any(ind in relevance for ind in direct_indicators):
        return "direct"

    query_words = set(query.lower().split())
    title_words = set(title.split())
    if len(query_words & title_words) >= 3:
        return "direct"

    supporting_indicators = ["related to", "similar approach", "applies to", "uses", "dataset for"]
    if any(ind in relevance for ind in supporting_indicators):
        return "supporting"

    return "background"

def _build_paper_block_with_classification(papers: list[dict], summaries: dict) -> str:
    """Build paper block with evidence type classification."""
    paper_parts = []
    for i, p in enumerate(papers):
        p["_idx"] = str(i) 
        abstract = p.get("text", sanitize_abstract(p.get("summary", " ")))
        if len(abstract) < 20 or "\x02" in abstract or "\x01" in abstract:
            abstract = f"[Abstract stripped. Paper: {p['title']}]"

        evidence_type = _classify_evidence_type(p, "", summaries)
        paper_parts.append(
            f"[paper_id={i}] [Evidence: {evidence_type.upper()}]\n"
            f"Title: {p['title']}\n"
            f"Abstract: {abstract[:1500]}"
        )
    return "\n\n".join(paper_parts)

def _summarize_papers(llm, papers: list[dict], query: str) -> dict:
    """Summarize papers and classify evidence type."""
    paper_block = _build_paper_block_with_classification(papers, {})

    batch_messages = [
        SystemMessage(
            content=(
                "You MUST return a JSON object with this EXACT structure:\n"
                '{\n'
                '  "summaries": [\n'
                '    {\n'
                '      "paper_id": "0",\n'
                '      "key_contribution": "what the paper proposed",\n'
                '      "methodology": "methods, datasets, evaluation",\n'
                '      "findings": "main results and findings",\n'
                '      "relevance_to_query": "how directly it addresses the query",\n'
                '      "evidence_type": "direct" | "supporting" | "background",\n'
                '      "key_metrics": ["exact numeric figures stated in the text, e.g. '
                '\'top-1 accuracy +2-4% over CNN\', \'published 2023\', \'O(N^2) attention cost\'"]\n'
                '    },\n'
                '    { "paper_id": "1", ... }\n'
                '  ]\n'
                '}\n\n'
                "CRITICAL: You MUST wrap the array in a 'summaries' key. "
                "Do NOT return just the array. "
                "All field names must be exactly as shown (lowercase, case-sensitive). "
                "paper_id MUST be a string, not a number.\n\n"
                "KEY_METRICS RULES:\n"
                "- Copy numbers/figures VERBATIM from the abstract/text — never estimate or infer.\n"
                "- Include comparative figures (e.g. accuracy deltas, FLOPs, latency, dataset sizes, "
                "parameter counts) if explicitly stated, even approximate ranges like '2-4%'.\n"
                "- If the paper states no such figures, return an empty list — do not fabricate."
            )
        ),
        HumanMessage(content=f"Query: {query}\n\n{paper_block}"),
    ]

    try:
        result: BatchPaperSummaries = llm.with_structured_output(BatchPaperSummaries).invoke(
            batch_messages, config={"timeout": 20}
        )
        summaries = {s.paper_id: s.model_dump() for s in result.summaries}

        for i, p in enumerate(papers):
            p["_idx"] = str(i)

        return summaries
    except Exception:
        return {
            str(i): {
                "paper_id": str(i),
                "key_contribution": p['title'],
                "methodology": "",
                "findings": "",
                "relevance_to_query": "",
                "evidence_type": "supporting",
                "key_metrics": []
            }
            for i, p in enumerate(papers)
        }

def _count_evidence_types(summaries: dict) -> dict:
    """Count papers by evidence type."""
    counts = {"direct": 0, "supporting": 0, "background": 0}
    for s in summaries.values():
        etype = s.get("evidence_type", "supporting")
        counts[etype] = counts.get(etype, 0) + 1
    return counts

def _select_top_references(papers: list[dict], summaries: dict, mode: str, max_refs: int = 5) -> list[str]:
    """Select most relevant paper IDs for references."""
    direct_ids = []
    supporting_ids = []

    for i, p in enumerate(papers):
        sid = str(i)
        if sid not in summaries:
            continue
        etype = summaries[sid].get("evidence_type", "supporting")
        if etype == "direct":
            direct_ids.append(sid)
        elif etype == "supporting":
            supporting_ids.append(sid)

    if mode == "normal":
        selected = direct_ids[:2] + supporting_ids[:1]
        return selected[:3]
    else:
        selected = direct_ids + supporting_ids
        return selected[:max_refs]

def _run_normal_mode(llm, state: AgentState, papers: list[dict], summaries: dict) -> NormalAnswer:
    """Generate concise but detailed normal mode answer."""
    evidence_counts = _count_evidence_types(summaries)
    n_direct = evidence_counts["direct"]
    n_supporting = evidence_counts["supporting"]

    if n_direct >= 2:
        evidence_strength = "High"
        strength_reason = "Multiple directly relevant studies found with consistent evidence."
    elif n_direct == 1:
        evidence_strength = "Medium"
        strength_reason = "Only one direct study found; lacks broader validation or comparisons."
    else:
        evidence_strength = "Low"
        strength_reason = "No direct studies found; relying on indirect or theoretical support."

    paper_block = "\n\n".join([
        f"[{i}] [{summaries.get(str(i), {}).get('evidence_type', 'supporting').upper()}] {p['title']}: {summaries.get(str(i), {}).get('key_contribution', '')}"
        for i, p in enumerate(papers)
    ])

    prompt = f"""You are a research assistant providing a direct but thorough answer.
QUERY: {state['query']}
EVIDENCE AVAILABLE:
Direct evidence: {n_direct} paper(s)
Supporting evidence: {n_supporting} paper(s)
PAPERS:
{paper_block}

You MUST return a JSON object with EXACTLY these field names (case-sensitive):
- "direct_answer": string (2-4 sentences directly answering the query)
- "brief_context": string or null (EXACTLY ONE sentence if strictly necessary, otherwise null)
- "evidence": string (detailed summary with markdown formatting)
- "limitations": array of strings (3-5 distinct methodological gaps)
- "conclusion": string (asks: what is supported, what remains uncertain, what future work)
- "confidence": "High" | "Medium" | "Low"
- "confidence_explanation": string
- "references": array of paper_id strings

DO NOT use field names like "answer", "context", "CONFIDENCE", "Limitations", or any variations.
USE EXACTLY the lowercase field names listed above.

CONFIDENCE RULES (CRITICAL - MUST BE CONSISTENT):
- If direct evidence >= 2: Confidence is "High".
- If direct evidence == 1: Confidence is "Medium". (Do NOT use High for a single study).
- If direct evidence == 0: Confidence is "Low".

CRITICAL RULES:
- Do NOT claim a paper solves the problem unless it explicitly does.
- Do NOT combine unrelated papers into a fictional framework.
- If evidence is weak, explicitly state that in the Conclusion.
{_evidence_mode_instruction(state.get("evidence_mode", "literature"))}
{LATEX_INSTRUCTION}"""

    try:
        answer = _invoke_structured_with_repair(
            llm,
            [
                SystemMessage(content="Respond with ONLY a function call to NormalAnswer. No text before or after."),
                HumanMessage(content=prompt)
            ],
            NormalAnswer,
            max_retries=2
        )
        if answer is None:
            raise ValueError("Failed to generate valid NormalAnswer after retries")

        answer.confidence = evidence_strength
        answer.confidence_explanation = strength_reason
        return answer
    except Exception as e:
        print(f"[summarize] Normal mode failed: {e}")
        return NormalAnswer(
            direct_answer="I could not generate a structured answer due to a processing error.",
            brief_context=None,
            evidence="",
            limitations=["Processing error occurred."],
            conclusion="Please try again.",
            confidence="Low",
            confidence_explanation="Processing error.",
            references=[]
        )

def _run_researched_mode(llm, state: AgentState, papers: list[dict], summaries: dict) -> ResearchAnswer:
    """Generate detailed research mode answer."""
    evidence_counts = _count_evidence_types(summaries)
    n_direct = evidence_counts["direct"]
    n_total = len(papers)

    paper_block = "\n\n".join([
        f"[{i}] [{summaries.get(str(i), {}).get('evidence_type', 'supporting').upper()}] {p['title']}: {summaries.get(str(i), {}).get('key_contribution', '')}"
        for i, p in enumerate(papers)
    ])

    include_comparative = n_direct >= 2

    user_query_lower = state['query'].lower()
    explicitly_wants_table = any(w in user_query_lower for w in ("table", "tabular", "tabulate"))

    table_instruction = ""
    if explicitly_wants_table:
        table_instruction = (
            "\n\nTABLE REQUIREMENT (MANDATORY — the user explicitly asked for a table):\n"
            "You MUST include a markdown table in the COMPARATIVE ANALYSIS field. "
            "The table must compare what the user actually asked to compare "
            f"(re-read the query: \"{state['query']}\") — if the user asked to "
            "compare architectures/methods/models (e.g. 'compare CNNs and ViTs'), "
            "the table rows must be comparison DIMENSIONS (e.g. accuracy, compute "
            "cost, data efficiency, interpretability) with one column per "
            "architecture/method being compared, populated with real findings "
            "cited via [paper_id=N] — NOT a list of the source papers themselves. "
            "Only build a table of the papers themselves if the user explicitly "
            "asked to compare the papers/studies/literature directly."
        )

    prompt = f"""You are a domain researcher writing a detailed literature review.
QUERY: {state['query']}
EVIDENCE AVAILABLE:
Total papers: {n_total}
Direct evidence: {n_direct} paper(s)
Supporting evidence: {evidence_counts['supporting']} paper(s)
PAPERS:
{paper_block}

You MUST return a JSON object with EXACTLY these field names (case-sensitive):
- "executive_summary": string
- "background_concepts": string
- "related_research": string
- "literature_review": string
- "comparative_analysis": string or null
- "evidence_assessment": string
- "research_gaps": string
- "practical_implications": string
- "final_answer": string
- "confidence": "High" | "Medium" | "Low"
- "confidence_explanation": string
- "references": array of paper_id strings

DO NOT use field names like "ExecutiveSummary", "BACKGROUND", or any other casing variations.
USE EXACTLY the lowercase field names listed above.

Content per field:
1. EXECUTIVE SUMMARY: High-level summary of what literature supports, what is uncertain, and the final answer.
2. BACKGROUND CONCEPTS: Explain concepts from general → specific. Teach before evaluating. Only include what's relevant.
3. RELATED RESEARCH: Briefly cover adjacent areas and explain their relevance to the question.
4. LITERATURE REVIEW: Synthesize key papers (methods, datasets, metrics, findings). Synthesize, do NOT just list papers one by one.
5. COMPARATIVE ANALYSIS {'(REQUIRED - multiple direct studies exist)' if include_comparative else '(OPTIONAL - include only if meaningful)'}: Compare methods, datasets, or findings. Use a markdown table if helpful.
6. EVIDENCE ASSESSMENT: Discuss strength, consistency, and limitations of current evidence.
7. RESEARCH GAPS: Identify genuine unanswered questions or missing areas.
8. PRACTICAL IMPLICATIONS: Actionable implications. Clearly separate established evidence from speculation.
9. FINAL ANSWER: The definitive, synthesized answer to the user's original question.

FORMATTING REQUIREMENTS:
- Use proper markdown formatting throughout.
- Use ## for section headers.
- Use bullet points (- item) for lists.
- Each paragraph should be separated by a blank line.
- Do NOT write a "References", "Bibliography", or "Works Cited" section
  anywhere in any field. The application appends a single formatted
  references list automatically after your answer — writing your own
  creates a duplicate, messy list. Only use inline [paper_id=N] citations.
{table_instruction}

CRITICAL RULES:
- Synthesize literature instead of listing papers.
- Support claims with citations (use [paper_id=N] format).
- Clearly distinguish established evidence from speculation.
- Do NOT combine unrelated studies into fictional frameworks.
- If no direct evidence exists, state "No direct evidence was found" and explain the closest research.
{_evidence_mode_instruction(state.get("evidence_mode", "literature"))}
{LATEX_INSTRUCTION}
Generate a ResearchAnswer JSON object matching the schema exactly."""

    try:
        answer = _invoke_structured_with_repair(
            llm,
            [
                SystemMessage(content="Respond with ONLY a function call to ResearchAnswer. No text before or after."),
                HumanMessage(content=prompt)
            ],
            ResearchAnswer,
            max_retries=2
        )
        if answer is None:
            raise ValueError("Failed to generate valid ResearchAnswer after retries")

        if not include_comparative:
            answer.comparative_analysis = None
        return answer
    except Exception as e:
        print(f"[summarize] Research mode failed: {e}")
        return ResearchAnswer(
            executive_summary="Processing error occurred.",
            background_concepts="",
            related_research="",
            literature_review="",
            comparative_analysis=None,
            evidence_assessment="",
            research_gaps="",
            practical_implications="",
            final_answer="I could not generate a structured answer due to a processing error.",
            confidence="Low",
            confidence_explanation="Processing error.",
            references=[]
        )

_PAPER_AS_SUBJECT_PATTERNS = (
    "compare the papers", "compare these papers", "compare papers",
    "compare the studies", "compare these studies", "compare studies",
    "table of papers", "table of the papers", "table of studies",
    "compare the retrieved papers", "compare retrieved papers",
    "papers comparison", "studies comparison",
    "list the papers", "summarize the papers in a table",
    "table comparing the papers", "table comparing papers",
    "table comparing the studies", "table comparing studies",
)


def _wants_paper_comparison_table(query: str) -> bool:
    """True only when the user explicitly asks to compare the RETRIEVED
    PAPERS/STUDIES THEMSELVES as the subject of the table (title/year/
    contribution/methodology per paper) — e.g. 'compare these papers in a
    table'. This is intentionally narrow: a query like 'compare CNNs and
    ViTs... from the retrieved papers' is asking to compare CNNs vs ViTs
    (a table of comparison DIMENSIONS with citations), not a table listing
    the papers — incidental words like 'paper'/'research' anywhere in the
    query must NOT trigger this path, or the wrong table gets substituted
    in for whatever the LLM's comparative_analysis field produced."""
    q = query.lower()
    return any(pattern in q for pattern in _PAPER_AS_SUBJECT_PATTERNS)


def _generate_fallback_table(papers: list[dict], summaries: dict, query: str) -> str | None:
    """Generate a basic comparison table from papers, used ONLY as a last
    resort when the query explicitly asked to compare the papers themselves
    (see _wants_paper_comparison_table) and the LLM produced no table at all."""
    if len(papers) < 2:
        return None

    lines = ["| # | Paper | Year | Key Contribution | Methodology |", "|---|-------|------|------------------|-------------|"]
    for i, p in enumerate(papers[:6]):
        sid = str(i)
        summary = summaries.get(sid, {})
        year = p.get('published', '')
        if year and len(year) > 4:
            year = year[:4]

        title = p.get('title', '')
        contribution = summary.get('key_contribution', '')[:90]
        methodology = summary.get('methodology', '')[:90]

        lines.append(
            f"| {i+1} | {title[:50]}{'...' if len(title)>50 else ''} "
            f"| {year or 'N/A'} | {contribution}{'...' if len(summary.get('key_contribution',''))>90 else ''} "
            f"| {methodology}{'...' if len(summary.get('methodology',''))>90 else ''} |"
        )

    return "\n".join(lines)


def _stitch_normal_answer(answer: NormalAnswer) -> str:
    """Format normal mode answer."""
    parts = []
    parts.append(f"## Direct Answer\n\n{answer.direct_answer}\n")

    if answer.brief_context:
        parts.append(f"## Brief Context\n\n{answer.brief_context}\n")

    evidence = answer.evidence.replace("\\n", "\n")
    parts.append(f"## Evidence\n\n{evidence}\n")

    if answer.limitations:
        parts.append("## Limitations\n")
        for lim in answer.limitations:
            parts.append(f"- {lim}")
        parts.append("")

    conclusion = answer.conclusion.replace("\\n", "\n")
    parts.append(f"## Conclusion\n\n{conclusion}\n")
    parts.append(f"**Confidence**: {answer.confidence} – {answer.confidence_explanation}\n")

    return "\n".join(parts)


def _strip_headers(text: str) -> str:
    """Strip leading markdown headers from LLM-generated field content."""
    if not text:
        return text
    lines = text.split('\n')
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if re.match(r'^#{1,4}\s+\S', stripped) and len(stripped) < 60:
            continue
        cleaned.append(line)
    return '\n'.join(cleaned)


def _stitch_research_answer(answer: ResearchAnswer) -> str:
    """Format research mode answer with proper markdown."""
    parts = []

    fields = [
        ("Executive Summary", answer.executive_summary),
        ("Background Concepts", answer.background_concepts),
        ("Related Research", answer.related_research),
        ("Literature Review", answer.literature_review),
        ("Comparative Analysis", answer.comparative_analysis),
        ("Evidence Assessment", answer.evidence_assessment),
        ("Research Gaps", answer.research_gaps),
        ("Practical Implications", answer.practical_implications),
        ("Final Answer", answer.final_answer),
    ]

    for section_name, field_value in fields:
        if not field_value:
            continue
        content = field_value.replace(chr(92)+'n', chr(10))
        content = _strip_headers(content)
        if section_name == "Research Gaps":
            content = re.sub(r'\d+\)\s*', '- ', content)
        parts.append(f"## {section_name}\n\n{content}\n")

    ce = answer.confidence_explanation.replace(chr(92)+'n', chr(10))
    parts.append(f"## Confidence: {answer.confidence}\n\n{ce}\n")

    return "\n".join(parts)

def summarize_node(state: AgentState) -> AgentState:
    llm = get_llm(temperature=0)
    papers = state["ranked_papers"]
    mode = state.get("response_mode", "normal")

    if not papers:
        if mode == "researched":
            final = _run_researched_mode(llm, state, [], {})
            answer_text = _stitch_research_answer(final)
        else:
            final = _run_normal_mode(llm, state, [], {})
            answer_text = _stitch_normal_answer(final)

        return {
            **state,
            "final_answer": answer_text,
            "coverage_gaps": state.get("search_terms", []),
            "references": [],
        }

    summaries = _summarize_papers(llm, papers, state["query"])

    if mode == "researched":
        final = _run_researched_mode(llm, state, papers, summaries)
        answer_text = _stitch_research_answer(final)
        ref_ids = final.references if final.references else _select_top_references(papers, summaries, mode, max_refs=8)

        user_wants_table = _wants_paper_comparison_table(state['query'])
        if user_wants_table and not final.comparative_analysis:
            fallback = _generate_fallback_table(papers, summaries, state['query'])
            if fallback:
                answer_text += f"\n\n## Comparative Analysis\n\n{fallback}\n"
    else:
        final = _run_normal_mode(llm, state, papers, summaries)
        answer_text = _stitch_normal_answer(final)
        ref_ids = final.references if final.references else _select_top_references(papers, summaries, mode, max_refs=3)

    evidence_mode = state.get("evidence_mode", "literature")
    references = build_references(papers)

    if evidence_mode == "uploaded":
        references = [r for r in references if r.get("source") == "user_upload"]

    id_map = paper_id_to_ref_id_map(papers, references)
    answer_text = rewrite_inline_citations(answer_text, id_map)

    selected_refs = [r for i, r in enumerate(references) if str(i) in ref_ids] if references else []

    frontend_references = references if mode == "researched" else selected_refs

    if mode == "researched" and frontend_references:
        answer_text = re.sub(
            r'\n\n(?:---\n\n)?#{0,4}\s*\*{0,2}(?:References|Bibliography|Works Cited)\*{0,2}\s*\n.*',
            '',
            answer_text,
            flags=re.DOTALL | re.IGNORECASE
        ).strip()
        answer_text = answer_text + "\n\n---\n\n**References**\n\n" + format_reference_block(frontend_references)

    domain_caveat = state.get("domain_caveat")
    if state.get("low_confidence_results"):
        low_conf_note = (
            "Few strongly relevant papers were found, so the relevance threshold was relaxed. "
            "Treat this answer as a starting point rather than a comprehensive review."
        )
        domain_caveat = f"{domain_caveat} {low_conf_note}" if domain_caveat else low_conf_note

    return {
        **state,
        "summaries": summaries,
        "final_answer": answer_text,
        "coverage_gaps": [],
        "domain_caveat": domain_caveat,
        "references": frontend_references,
    }