# Backend ownership audit

Status: baseline audit for Phase 1.1. This document records whether each
backend route reads or writes user data and whether ownership is enforced by
the authenticated user's `user_id`.

## Enforcement legend

- **Scoped**: the route queries a persistent row with both the resource ID and
  the authenticated `user_id`.
- **Auth-only**: the route requires an authenticated session, but the legacy
  storage key is supplied by the client and is not joined to a user-owned
  database row.
- **Not applicable**: the route does not access user-owned data.

## Authentication and PostgreSQL-owned resources

| Route | Reads | Writes | Ownership status |
| --- | --- | --- | --- |
| `POST /api/auth/signup` | Account input | User and session | Not applicable during account creation |
| `POST /api/auth/login` | User and session rows | Session row | Scoped by normalized email and session user |
| `POST /api/auth/logout` | Current session | Revokes current session | Scoped by hashed session cookie |
| `POST /api/auth/logout-all` | Current user sessions | Revokes all user sessions | Scoped by authenticated `user_id` |
| `GET /api/auth/me` | Current user | None | Scoped by authenticated session |
| `GET /api/chats` | User chats | None | **Scoped** |
| `GET /api/chats/{chat_id}` | Chat and messages | None | **Scoped**; inaccessible chats return 404 |
| `PATCH /api/chats/{chat_id}` | User chat | Chat title | **Scoped**; inaccessible chats return 404 |
| `DELETE /api/chats/{chat_id}` | User chat | Soft-deletes chat | **Scoped**; inaccessible chats return 404 |
| `GET /api/library` | User papers | None | **Scoped** |
| `POST /api/library` | Current user | Paper row | **Scoped** |
| `DELETE /api/library/{paper_id}` | User paper | Deletes paper row | **Scoped** |

## Legacy research and session-backed routes

These routes are protected by the authenticated dependency in
`backend/app/main.py`, but their underlying Chroma, Neo4j, in-memory, upload,
or filename stores are keyed by a client-provided `session_id`, `turn_id`,
`visual_id`, or filename. They require migration to a user-owned persistent
resource before they can be considered isolated.

| Route | Reads user data? | Writes user data? | Current status |
| --- | --- | --- | --- |
| `POST /api/research` | Session papers/history | Research session, vector/graph state | **Auth-only**; session ID is client supplied |
| `POST /api/graph/{session_id}/view` | Graph/session papers | None | **Auth-only** |
| `POST /api/graph/{session_id}/path` | Graph/session papers | None | **Auth-only** |
| `GET /api/graph/{session_id}/suggest` | Graph/session papers | None | **Auth-only** |
| `POST /api/graph/{session_id}/query` | Graph/session papers | None | **Auth-only** |
| `GET /api/graph/{session_id}/ensure` | Session graph | Graph state | **Auth-only** |
| `GET /api/graph/{session_id}/clusters` | Session graph | None | **Auth-only** |
| `GET /api/graph/{session_id}/contradictions` | Session graph | None | **Auth-only** |
| `GET /api/graph/paper/focus` | Paper graph neighborhood | None | **Auth-only**; paper URL is client supplied |
| `GET /api/graph/{session_id}/full` | Session graph | None | **Auth-only** |
| `GET /api/graph/{session_id}/turn/{turn_id}/full` | Turn graph | None | **Auth-only** |
| `POST /api/chat` | Session context | Chat/messages and legacy state | **Partially scoped**; PostgreSQL chat is checked, legacy stores remain |
| `POST /api/chat/stream` | Session context | Streaming chat/messages and legacy state | **Partially scoped** |
| `POST /api/chat/cancel/{request_id}` | Cancellation registry | Cancellation state | **Auth-only**; request IDs are process-local |
| `POST /api/chat/regenerate` | Session context | New assistant response | **Partially scoped** |
| `POST /api/followup` | Session papers/history | None or legacy state | **Auth-only** |
| `POST /api/followup/stream` | Session papers/history | Streaming state | **Auth-only** |
| `POST /api/followup/cancel/{request_id}` | Cancellation registry | Cancellation state | **Auth-only** |
| `POST /api/upload` | Uploaded session context | Disk, vector, and graph state | **Auth-only**; session ID and filename are client supplied |
| `POST /api/upload/stream` | Uploaded session context | Disk, vector, and graph state | **Auth-only** |
| `GET /api/uploads/{session_id}/{filename}` | Uploaded PDF | None | **Auth-only**; no user ownership check |
| `DELETE /api/uploads/{session_id}` | Uploaded session context | Disk, vector, and graph state | **Auth-only** |
| `POST /api/upload/cancel/{request_id}` | Cancellation registry | Cancellation state | **Auth-only** |
| `GET /api/filename/{turn_id}` | Filename store | None | **Auth-only**; turn ID is client supplied |
| `POST /api/export/pdf` | Request body and referenced assets | Exported PDF on disk | **Auth-only**; answer/chart inputs are client supplied |

## Studio routes

Studio visuals are currently stored in the process-local `_REGISTRY` keyed by
`visual_id`. The request contains the session ID and optional conversation or
paper context, but no persistent ownership relation exists.

| Route | Reads user data? | Writes user data? | Current status |
| --- | --- | --- | --- |
| `POST /api/studio/generate` | Request-provided visual | Process-local visual registry and rendered asset | **Auth-only** |
| `POST /api/studio/generate/grounded` | Session papers/web results | Process-local registry and rendered asset | **Auth-only** |
| `POST /api/studio/draft` | Session papers/conversation | Rendered preview asset | **Auth-only** |
| `POST /api/studio/{visual_id}/revise` | Existing visual | Process-local registry | **Auth-only** |
| `GET /api/studio/{visual_id}` | Existing visual | None | **Auth-only** |
| `GET /api/studio/session/{session_id}` | Session visuals | None | **Auth-only** |

## Required remediation

1. Introduce persistent user-owned records for uploaded papers/files,
   research sessions, turns, and Studio visuals.
2. Add `user_id` foreign keys and indexes before making those columns
   non-null; safely backfill only rows with an unambiguous owner.
3. Reject or quarantine legacy rows without an owner rather than assigning
   them to an arbitrary account.
4. Change every legacy read/write/delete query to include the authenticated
   `user_id`, returning 404 for an inaccessible resource.
5. Add cross-user tests for every route listed as **Auth-only** or
   **Partially scoped**.
