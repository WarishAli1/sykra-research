from typing import Iterable, Set


CAPABILITY_PROVIDERS = {
    "primary_research": {
        "openalex",
        "arxiv",
    },
    "secondary_research": {
        "openalex",
        "arxiv",
    },
    "official_authority": {
        "web",
    },
    "official_authority_clinical": {
        "web",
    },
    "official_authority_legal": {
        "web",
    },
    "official_authority_financial": {
        "web",
    },
    "technical_documentation": {
        "web",
    },
    "current_information": {
        "web",
    },
    "standards": {
        "web",
    },
    "statistics": {
        "web",
    },
}


DEFAULT_PROVIDERS = {
    "openalex",
    "arxiv",
    "web",
}


def providers_for_capabilities(capabilities: Iterable[str]) -> Set[str]:
    """
    Resolve abstract evidence capabilities into provider types.

    This is provider infrastructure only.

    It must not inspect the user query.
    It must not classify domains.
    It must not call external APIs.
    """
    providers: Set[str] = set()

    for capability in capabilities or []:
        capability = str(capability or "").strip()

        if not capability:
            continue

        providers.update(
            CAPABILITY_PROVIDERS.get(
                capability,
                set(),
            )
        )

    if not providers:
        return set(DEFAULT_PROVIDERS)

    return providers


def web_source_intent_for_capabilities(capabilities: Iterable[str]) -> str:
    """
    Map evidence capabilities to the web_search source-intent label.

    This remains infrastructure-level mapping only.
    """
    caps = {
        str(c or "").strip()
        for c in (capabilities or [])
        if str(c or "").strip()
    }

    if "official_authority_clinical" in caps:
        return "clinical_medical"

    if "official_authority_legal" in caps:
        return "legal_policy"

    if "official_authority_financial" in caps:
        return "financial_economic"

    if (
        "official_authority" in caps
        or "technical_documentation" in caps
        or "standards" in caps
    ):
        return "technical_standards"

    if "current_information" in caps or "statistics" in caps:
        return "industry_market"

    return "academic"