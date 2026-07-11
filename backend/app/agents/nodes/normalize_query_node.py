from langchain_core.messages import SystemMessage, HumanMessage
from app.agents.state import AgentState
from app.agents.schemas import NormalizedQuery
from app.services.llm_client import get_cheap_llm


def normalize_query_node(state: AgentState) -> AgentState:
    llm = get_cheap_llm(temperature=0)
    structured_llm = llm.with_structured_output(NormalizedQuery)

    prompt = f"""Break the query into 5 distinct search phrases that could retrieve relevant papers.
- Each phrase MUST include the domain or its synonyms if a domain is specified (e.g., 'in NLP').
- Vary the phrasing: use full task names, abbreviations, related concepts.
- If no domain is specified, just output 5 query variations.

Also, if the query explicitly specifies a domain (e.g. 'in NLP', 'for computer vision'),
output:
- domain_full: the domain's full name (e.g. 'natural language processing', 'computer vision').
- domain_keywords: a short list of 2-4 domain-specific keywords that characterize the field
  (e.g. ['language', 'text', 'nlp'] for NLP, or ['vision', 'image', 'visual'] for CV).
- mandatory_domain_keywords: 2-3 words that a paper's abstract MUST contain to be considered
  relevant to this domain. For NLP: ['language', 'text', 'nlp'].
If no domain is mentioned, set domain_full to null, domain_keywords to empty, and mandatory_domain_keywords to null.

Set likely_cs_relevant to true if this query is about computer science, physics, math, or engineering
(where arXiv preprints are a normal source). Set it to false for health, medicine, biology, law,
social science, business, or other non-CS domains.

Always expand any acronym to its full technical name (e.g. "GAN" -> "generative adversarial network",
"CFG" -> "classifier-free guidance", "RAG" -> "retrieval augmented generation") — do this for
ANY acronym you recognize, not just common ones. If genuinely unsure what an acronym means,
keep it as-is rather than guessing.

User query: {state['query']}

Examples:
"Explain few-shot learning in NLP" -> search_terms: ["few-shot learning natural language processing", "prompt-based few-shot learning text classification", "in-context learning language models", "few-shot NLP transfer learning", "meta-learning for NLP tasks"], is_definitional: true, likely_cs_relevant: true, domain_full: "natural language processing", domain_keywords: ["language", "text", "nlp"], mandatory_domain_keywords: ["language", "text", "nlp"]
"Explain diffusion models and how they differ from GANs" -> search_terms: ["diffusion models", "generative adversarial networks", "score-based generative models", "diffusion vs GAN comparison", "denoising diffusion probabilistic models"], is_definitional: true, likely_cs_relevant: true, domain_full: null, domain_keywords: [], mandatory_domain_keywords: null
"Effectiveness of metformin in prediabetes patients" -> search_terms: ["metformin prediabetes clinical trial", "metformin diabetes prevention", "prediabetes treatment metformin", "metformin glycemic control prediabetes", "metformin prediabetes systematic review"], is_definitional: false, likely_cs_relevant: false, domain_full: null, domain_keywords: [], mandatory_domain_keywords: null
"""
    messages = [
        SystemMessage(content="You must extract search terms from the user query using the NormalizedQuery function. Return a valid function call with no additional text."),
        HumanMessage(content=prompt),
    ]
    result: NormalizedQuery = structured_llm.invoke(messages)
    return {
        **state,
        "search_terms": result.search_terms,
        "is_definitional": result.is_definitional,
        "likely_cs_relevant": result.likely_cs_relevant,
        "domain_full": result.domain_full,
        "domain_keywords": result.domain_keywords,
        "mandatory_domain_keywords": result.mandatory_domain_keywords,
    }