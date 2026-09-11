"""`notify_inbound` must deliver the whole artifact, whatever shape its body is.

⛔ WHAT WAS WRONG. The tool advertises itself as notifying about "any inbound artifact", but it
assumed the body was JSON:

    content = json.loads(content_str)          # a dict -> a table
    except: content = {"raw": content_str[:500]}   # anything else -> CUT AT 500

Every artifact of a `+json` vendor type renders as plain TEXT by design, and that is exactly what
the website leads store. So the exception branch was not an edge case, it was the normal path.
Measured against the live corpus on 2026-09-10: 20 leads, one of them **709 characters** — over
the cap, and the long ones are the ones with something to say.

The subject degraded the same way: `_inbound_subject` read `content["email"]`, which a string
does not have, so every text-bodied lead was announced as `[Agience] Contact form (11111111)` —
an artifact id where the person's address belongs.

Both are the same mistake — one shape assumed for a field that carries two — so both are pinned
here together.
"""
from __future__ import annotations

import json

from agience_chorus.iris import server


# The real shape `www.agience.ai/bff/lead_artifacts._readable()` writes.
LEAD_TEXT = (
    "Robin Vance <robin.vance@northgate.invalid>\n"
    "\n"
    "—\n"
    "source    website-contact\n"
    "received  2026-09-10T12:00:00+00:00\n"
    "\n"
    "company   Northgate Supply\n"
    # ⛔ THE TAIL MUST BE UNIQUE. This padding was a single phrase repeated 14 times, so
    # `LEAD_TEXT[-40:]` also occurred inside the first 500 characters — and the "was it
    # truncated?" assertion passed on truncated output, because it found the tail earlier in
    # the body. A repetitive fixture silently disarms a substring check.
    "message   " + " ".join(f"point-{n} about the deployment." for n in range(1, 22))
    + " FINAL-MARKER-9c3f1e"
)


def test_the_sample_is_actually_over_the_old_cap():
    """Guard on the guard: if this body were short, every assertion below would pass trivially."""
    assert len(LEAD_TEXT) > 500, "the regression sample must exceed the 500-char truncation"


def test_the_samples_tail_is_unique():
    """⛔ AND THE TAIL MUST NOT APPEAR EARLIER. With a repetitive body, "is the tail present?"
    finds it inside the first 500 characters and reports success on truncated output. That is
    exactly what happened, and it made the truncation test pass against the broken code."""
    assert LEAD_TEXT.count("FINAL-MARKER-9c3f1e") == 1
    assert LEAD_TEXT[:500].find(LEAD_TEXT[-40:]) == -1, "the tail also occurs before the cap"


class _FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _FakeClient:
    """Stands in for `httpx.AsyncClient` so the REAL `notify_inbound` runs end to end."""

    def __init__(self, payload):
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, *a, **k):
        return _FakeResponse(self._payload)


def _run_notify(monkeypatch, content, context=None):
    """Drive the actual tool and capture what it hands to `send_email`.

    ⛔ THE POINT. An earlier version of this file asserted against `html.escape(...)` called by the
    TEST — which is the test proving its own arithmetic. It passed identically whether or not
    `notify_inbound` truncated anything. The rendering is only pinned if the tool does it.
    """
    import asyncio

    payload = {"content": content, "context": json.dumps(context or {"source": "website-contact"})}
    monkeypatch.setattr(server, "_require_user_headers", lambda: {})
    monkeypatch.setattr(server.httpx, "AsyncClient", lambda *a, **k: _FakeClient(payload))

    seen = {}

    async def _capture(*, to, subject, body_html, authorizer_artifact_id=""):
        seen.update(to=to, subject=subject, body_html=body_html)
        return json.dumps({"sent": True})

    monkeypatch.setattr(server, "send_email", _capture)
    asyncio.run(server.notify_inbound(
        artifact_id="11111111-2222-4333-8444-555555555555",
        workspace_id="b1fefeae-491a-4cc4-a807-311ee8a04261",
        notify_to="connect@agience.ai",
    ))
    assert seen, "notify_inbound never reached send_email — the harness is broken, not the code"
    return seen


def test_a_text_body_is_not_truncated(monkeypatch):
    """⛔ THE REGRESSION, through the real tool. The tail of the message must reach the email."""
    seen = _run_notify(monkeypatch, LEAD_TEXT)
    import html as _html
    assert "FINAL-MARKER-9c3f1e" in seen["body_html"], "the end of the lead was lost"
    assert _html.escape(LEAD_TEXT[-40:]) in seen["body_html"]
    assert "Northgate Supply" in seen["body_html"]


def test_the_real_tool_escapes_a_hostile_body(monkeypatch):
    """A lead's message is written by a stranger and lands in an HTML email."""
    hostile = 'Ada <ada@example.com>\nmessage   <script>alert("x")</script>'
    seen = _run_notify(monkeypatch, hostile)
    assert "<script>" not in seen["body_html"]
    assert "&lt;script&gt;" in seen["body_html"]


def test_the_real_tool_subjects_a_text_lead_with_the_address(monkeypatch):
    seen = _run_notify(monkeypatch, LEAD_TEXT)
    assert "robin.vance@northgate.invalid" in seen["subject"]


def test_a_dict_body_still_renders_as_a_table(monkeypatch):
    """The JSON path is unchanged — fixing text must not break dicts."""
    seen = _run_notify(monkeypatch, json.dumps({"email": "someone@example.com", "company": "Acme"}))
    assert "<table" in seen["body_html"]
    assert "someone@example.com" in seen["body_html"]
    assert "Acme" in seen["body_html"]


def test_the_subject_names_the_person_not_the_artifact():
    """A text body still yields the submitter's address."""
    subject = server._inbound_subject(LEAD_TEXT, "website-contact", "11111111-2222-4333-8444")
    assert "robin.vance@northgate.invalid" in subject
    assert "11111111" not in subject, "fell back to the artifact id despite an address being present"


def test_a_dict_body_still_behaves_as_before():
    """The JSON path is unchanged — this change must not fix text by breaking dicts."""
    subject = server._inbound_subject(
        {"email": "someone@example.com", "name": "Someone"}, "website-contact", "abcdef12")
    assert "someone@example.com" in subject


def test_text_with_no_address_falls_back_to_the_artifact_id():
    """No address to find is not a failure; it is the case the id fallback exists for."""
    subject = server._inbound_subject("just a note, no address here", "webhook", "abcdef1234")
    assert "abcdef12" in subject
