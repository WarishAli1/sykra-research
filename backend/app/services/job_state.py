from __future__ import annotations


def pause_plan(plan: list[dict]) -> list[dict]:
    return [
        {**item, "status": "pending" if item.get("status") == "running" else item.get("status", "pending")}
        for item in plan
    ]


def resume_plan(plan: list[dict]) -> list[dict]:
    return [item for item in plan if item.get("status") != "done"]


def resume_chat_content(content: str, status: str) -> dict:
    return {
        "content": content,
        "streaming": status == "streaming",
        "retry": status in {"interrupted", "failed", "stopped"},
    }


def delete_file_cascade_counts(*, references: int, chunks: int, embeddings: int) -> dict[str, int]:
    return {"references": references, "chunks": chunks, "embeddings": embeddings}
