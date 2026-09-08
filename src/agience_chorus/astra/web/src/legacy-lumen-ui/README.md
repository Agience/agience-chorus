# legacy-lumen-ui

**Status: reference only — not wired, not built, not imported by anything in facet.**

**lumen** is the wisdom/inference tekton in chorus. Its inference code lives as
lumen-tekton operator implementations (`agience-crystal/src/crystal/operators/impl/
reasoning.py` = op.reason, `.../retrieval.py` = op.retrieve); its UI surface belongs
here, in facet (facet is a crystal's face — the render runtime).

## Contents

- `lumen_chat_bff.py` — the chat UI shell (`_CHAT_HTML` + `GET /`) and the non-generation
  BFF surfaces from `agience-lumen/src/lumen/app.py`, verbatim:
  - `POST /api/login` — password login proxied to Origin (the IDP), returns the operator JWT
  - `GET /api/history` — chat history read from Mantle
    (`application/vnd.agience.chat-message+json` artifacts, grouped by session)
  - `POST /api/chat` / `POST /api/chat/stream` — 501-refusing stubs (no-models rule:
    lumen has no generation tier; a refusal is never softened into a canned reply)

## Integration notes

- The chat UI is a single self-contained HTML string (`_CHAT_HTML`); its fetch calls hit
  `/api/login`, `/api/history`, `/api/chat/stream` on the same origin (BFF pattern).
- Auth: the browser holds a raw JWT; `_bearer()` normalizes it. `/api/history` and
  `/api/chat*` require the host auth dependency; `/api/login` is open.
- The 501 stubs are deliberate: lumen has no generation tier, and the refusal-on-the-
  status-line reasoning documented in the file's docstrings is load-bearing for any
  integration.
