"""aria chat — the store-and-forward respond path (#2a): a host-injected `respond(query)` responder.

When a host wires the local reach runtime (ember requester + lumen `op.respond` provider +
`StoreCarrier` + a `PumpLoop`), it exposes a synchronous `respond(query)->evidence` (a
`beam.pump.resolve`-backed responder) and sets `main._RESPOND_CARRIER = {"respond": …}`. The bff
then answers real queries — while an honest-null evidence (answer=None, no substrate) still
degrades to offline, never fabricated. Pins:

  answers     — a respond callable returning real op.respond evidence ⇒ /api/chat returns {text, offline:False}.
  query-dep   — the exact user turn reaches the responder (not a canned reply).
  honest-null — a respond callable returning no answer ⇒ /api/chat reports no answer (never a
                fabricated reply).

The real `lumen.conversation.respond` omits `grounded` entirely and returns `answer: ""` for a need
that fires nothing — it does not return an explicit `grounded` or express the null as `None`. A
mock that only ever emits the well-formed shape cannot observe a gate that mishandles the real one,
so the shapes the tekton actually produces are pinned here alongside the tidy ones.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # persona dir → bare local import

import web_bff  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402


def _post(app, q: str) -> dict:
    with TestClient(app) as client:
        return client.post("/api/chat",
                           json={"params": {"messages": [{"role": "user", "content": q}]}}).json()


def test_respond_callable_answers(monkeypatch):
    mod = web_bff._load_bff_module()
    monkeypatch.setattr(mod, "_RESPOND_CARRIER",
                        {"respond": lambda q: {"answer": "A dog is a domesticated canine.",
                                               "grounded": True, "cited": []}})
    data = _post(mod.app, "what is a dog?")
    assert data.get("offline") is False
    assert data.get("text") == "A dog is a domesticated canine."
    assert data.get("grounded") is True


def test_respond_callable_is_query_dependent(monkeypatch):
    mod = web_bff._load_bff_module()
    monkeypatch.setattr(mod, "_RESPOND_CARRIER",
                        {"respond": lambda q: {"answer": "echo:" + q, "grounded": True}})
    assert _post(mod.app, "hello there").get("text") == "echo:hello there"


def test_respond_callable_honest_null_is_a_refusal_not_an_outage(monkeypatch):
    """answer=None ⇒ no fabricated reply — reported via `refused`, because the carrier is live.

    `offline` means exactly one thing: no carrier. The responder here answered (even though its
    answer was None), so a live model is connected, and `offline` is False."""
    mod = web_bff._load_bff_module()
    monkeypatch.setattr(mod, "_RESPOND_CARRIER",
                        {"respond": lambda q: {"answer": None, "grounded": False}})
    data = _post(mod.app, "what is a dog?")
    # The computed null is silence: an authored "why" would be a category invented here, not
    # measured, so the text comes back empty rather than pre-explained.
    assert (data.get("text") or "") == ""
    assert data.get("grounded") is False                     # honest null: nothing was grounded
    assert data.get("refused") is True
    assert data.get("offline") is False                      # the carrier is live
    # `reason` is not reported: a pre-baked category like "no_evidence" would mislabel an empty
    # query as a grounding failure when the payload itself was the cause. `refused` is derived from
    # the absence of answer text; a narrative label for it would be authored, not measured.
    assert "reason" not in data, "the pipeline must not label its own null"


# ── the shapes the real tekton emits ──────────────────────────────────────────────────────────────

def test_empty_string_answer_is_the_computed_null(monkeypatch):
    """`lumen.conversation.respond` returns `answer: ""` when nothing fires. An `is None` gate would
    walk past that and publish the empty string as a reply; this pins that the empty string is
    caught as the null."""
    mod = web_bff._load_bff_module()
    monkeypatch.setattr(mod, "_RESPOND_CARRIER",
                        {"respond": lambda q: {"answer": "", "cited": [], "activations": []}})
    data = _post(mod.app, "zzqxwv plorbnak")
    assert data.get("grounded") is False
    assert data.get("refused") is True
    # An "explained" null is invented prose; the computed null is silence.
    assert (data.get("text") or "") == ""
    assert not data.get("cited"), "a refusal cites nothing, because nothing grounded it"


def test_whitespace_answer_is_also_the_computed_null(monkeypatch):
    """Adversarial sibling: a gate fixed with `answer != ""` would still pass "  " straight through."""
    mod = web_bff._load_bff_module()
    monkeypatch.setattr(mod, "_RESPOND_CARRIER",
                        {"respond": lambda q: {"answer": "   \n ", "cited": []}})
    data = _post(mod.app, "anything")
    assert data.get("refused") is True
    assert data.get("grounded") is False


def test_absent_grounded_key_never_becomes_a_grounding_claim(monkeypatch):
    """The tekton omits `grounded`. An answer with no citations is not grounded, and no layer may
    say otherwise on the tekton's behalf — the default must not manufacture an assertion from that
    absence."""
    mod = web_bff._load_bff_module()
    monkeypatch.setattr(mod, "_RESPOND_CARRIER",
                        {"respond": lambda q: {"answer": "some text", "cited": []}})
    data = _post(mod.app, "what is a dog?")
    assert data.get("text") == "some text"                   # still delivered — it is not withheld
    assert data.get("grounded") is False                     # but not claimed as grounded


def test_absent_grounded_key_is_measured_from_the_citations(monkeypatch):
    """The positive half — without it the test above is satisfied by hard-coding False.
    Cited evidence and uncited evidence must land on opposite sides of the same default."""
    mod = web_bff._load_bff_module()
    monkeypatch.setattr(mod, "_RESPOND_CARRIER",
                        {"respond": lambda q: {"answer": "A member of the genus Canis.",
                                               "cited": ["cite.wordnet"]}})
    data = _post(mod.app, "what is a dog?")
    assert data.get("grounded") is True
    assert data.get("cited") == ["cite.wordnet"]


def test_explicit_grounded_from_the_tekton_wins_over_the_default(monkeypatch):
    """A tekton that measured its own grounding is the authority on it. The derived default is a
    fallback for silence, not an override of a stated measurement — otherwise this layer would be
    second-guessing a reading it never took."""
    mod = web_bff._load_bff_module()
    monkeypatch.setattr(mod, "_RESPOND_CARRIER",
                        {"respond": lambda q: {"answer": "text", "grounded": False,
                                               "cited": ["cite.wordnet"]}})
    assert _post(mod.app, "q").get("grounded") is False
