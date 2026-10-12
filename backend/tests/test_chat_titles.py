from app.services.chat_titles import _title_from_query


def test_chat_title_is_compact_and_whitespace_normalized():
    assert _title_from_query("  What   causes   citation errors?  ") == "What causes citation errors"
    assert _title_from_query("") == "New chat"
