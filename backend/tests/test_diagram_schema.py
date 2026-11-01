import pytest
from pydantic import ValidationError

from app.models.diagram_schema import DiagramDocumentModel


def _document(page_type="flowchart"):
    return {
        "schemaVersion": 2,
        "id": "doc",
        "title": "Test",
        "activePageId": "page",
        "updatedAt": "2026-11-01T00:00:00Z",
        "pages": [{
            "id": "page",
            "name": "Page 1",
            "diagramType": page_type,
            "nodes": [],
            "edges": [],
        }],
    }


@pytest.mark.parametrize("page_type", ["flowchart", "dfd", "architecture"])
def test_supported_page_types_validate(page_type):
    assert DiagramDocumentModel.model_validate(_document(page_type)).pages[0].diagramType == page_type


def test_active_page_must_exist():
    payload = _document()
    payload["activePageId"] = "missing"
    with pytest.raises(ValidationError):
        DiagramDocumentModel.model_validate(payload)


def test_unknown_fields_are_rejected():
    payload = _document()
    payload["unexpected"] = True
    with pytest.raises(ValidationError):
        DiagramDocumentModel.model_validate(payload)
