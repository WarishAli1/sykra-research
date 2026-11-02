from app.services.job_state import (
    delete_file_cascade_counts,
    pause_plan,
    resume_chat_content,
    resume_plan,
)


def test_pause_marks_running_section_pending_and_resume_keeps_done():
    plan = [{"id": "a", "status": "done"}, {"id": "b", "status": "running"}, {"id": "c", "status": "pending"}]
    paused = pause_plan(plan)
    assert [item["status"] for item in paused] == ["done", "pending", "pending"]
    assert [item["id"] for item in resume_plan(paused)] == ["b", "c"]


def test_chat_resume_shows_partial_content_and_retry_state():
    assert resume_chat_content("partial", "interrupted") == {
        "content": "partial",
        "streaming": False,
        "retry": True,
    }


def test_file_delete_cascade_tracks_all_storage_layers():
    assert delete_file_cascade_counts(references=2, chunks=4, embeddings=4) == {
        "references": 2,
        "chunks": 4,
        "embeddings": 4,
    }
