from app.services.report_document import (
    apply_operation,
    dedupe_sections,
    guide_diff,
    remove_all_content,
    remove_sections,
    strip_matching_heading,
)


def test_dedupe_sections_keeps_first_normalized_title():
    sections = [{"id": "a", "title": "Methods"}, {"id": "b", "title": " methods! "}]
    assert [s["id"] for s in dedupe_sections(sections)] == ["a"]


def test_remove_all_keeps_references_outside_sections():
    assert remove_all_content({
        "sections": [{"id": "a", "title": "Abstract", "content": "text"}],
        "references": [{"id": 1}],
    }) == {
        "sections": [{"id": "a", "title": "Abstract", "content": ""}],
        "references": [{"id": 1}],
    }


def test_guide_diff_fuzzy_matches_and_only_adds_missing():
    result = guide_diff([{"title": "Methods"}], ["Methodology", "Discussion"])
    assert result["kept"] == ["Methods"]
    assert result["added"] == ["Discussion"]
    assert result["removed"] == []


def test_heading_is_not_saved_in_section_body():
    assert strip_matching_heading("# Methods\nBody", "Methods") == "Body"


def test_scoped_remove_and_replace():
    sections = [{"id": "a", "title": "A", "content": "old"}, {"id": "b", "title": "B", "content": "keep"}]
    replaced = apply_operation(sections, "replace_section_content", ["a"], "# A\nnew")
    assert replaced[0]["content"] == "new"
    assert len(apply_operation(replaced, "remove_section", ["a"])) == 1
