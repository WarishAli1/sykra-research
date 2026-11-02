"""Pure report document operations shared by generation and editing."""

from __future__ import annotations

import re
from difflib import SequenceMatcher


def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.casefold()).strip()


def dedupe_sections(sections: list[dict]) -> list[dict]:
    result: list[dict] = []
    seen: set[str] = set()
    for section in sections:
        key = normalize_title(str(section.get("title", "")))
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(section)
    return result


def remove_sections(sections: list[dict], section_ids: set[str], remove_all: bool = False) -> list[dict]:
    if remove_all:
        return [{**section, "content": ""} for section in sections]
    return [section for section in sections if str(section.get("id", section.get("section_id"))) not in section_ids]


def remove_all_content(document: dict) -> dict:
    return {
        **document,
        "sections": [{**section, "content": ""} for section in document.get("sections", [])],
        "references": list(document.get("references", [])),
    }


def strip_matching_heading(content: str, title: str) -> str:
    lines = content.lstrip().splitlines()
    if lines and normalize_title(re.sub(r"^#{1,6}\s*", "", lines[0])) == normalize_title(title):
        return "\n".join(lines[1:]).lstrip()
    return content.strip()


def guide_diff(existing: list[dict], guide_titles: list[str]) -> dict[str, list[str]]:
    existing_titles = [str(section.get("title", "")) for section in existing]
    normalized_existing = {normalize_title(title): title for title in existing_titles}
    added: list[str] = []
    kept: list[str] = []
    matched_keys: set[str] = set()
    for title in guide_titles:
        normalized = normalize_title(title)
        if not normalized:
            continue
        match = next(
            (key for key in normalized_existing if key == normalized or SequenceMatcher(None, key, normalized).ratio() >= 0.65),
            None,
        )
        if match:
            kept.append(normalized_existing[match])
            matched_keys.add(match)
        elif title not in added:
            added.append(title.strip())
    removed = [title for key, title in normalized_existing.items() if key not in matched_keys]
    return {"added": added, "kept": list(dict.fromkeys(kept)), "removed": removed}


def extract_guide_titles(text: str) -> list[str]:
    titles: list[str] = []
    for line in (text or "").splitlines():
        value = re.sub(r"^#+\s*", "", line).strip(" -*\t")
        value = re.sub(r"^(?:section|chapter)\s+\d+(?:\.\d+)*[:.)-]?\s*", "", value, flags=re.I)
        if 2 <= len(value.split()) <= 12 and value and not value.endswith((".", ":", ";")):
            titles.append(value[:200])
    return list(dict.fromkeys(titles))


def apply_operation(sections: list[dict], operation: str, section_ids: list[str], content: str = "", title: str = "") -> list[dict]:
    ids = set(section_ids)
    if operation == "remove_section":
        return remove_sections(sections, ids)
    if operation == "replace_section_content":
        return [
            {**section, "content": strip_matching_heading(content, str(section.get("title", "")))}
            if str(section.get("id", section.get("section_id"))) in ids else section
            for section in sections
        ]
    if operation == "add_section":
        return dedupe_sections([*sections, {"id": title or f"section-{len(sections)+1}", "title": title, "content": content}])
    if operation == "rewrite_all":
        return [{**section, "content": strip_matching_heading(content, str(section.get("title", "")))} for section in sections]
    return sections
