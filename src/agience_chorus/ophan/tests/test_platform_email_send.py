"""Ophan platform email sends (receipts / usage warnings).

`_send_account_email` acts as the operator-rooted system principal: it resolves
the recipient via Origin, obtains a system delegation from the exchange, and
invokes the platform email operator under that delegation. It is best-effort —
a send failure must never break the caller (e.g. a Stripe webhook).
"""
from __future__ import annotations

import json

import pytest

# 2026-08-26: a dead `sys.path` insert stood here and is removed. MEASURED per file — the
# inserts were neutralised, this file's tests run, and it passed; the full chorus suite then
# confirmed no global side effect (861 passed). `pytest.ini:34` (`pythonpath = src`) is what
# puts `src` on the path. Eight sibling test files KEEP theirs and must — see
# `agience-build/tighten/STATE.json`, finding `thirty-five-dead-path-inserts`.


# 2026-08-26: an inline `spec_from_file_location` loader stood here. `src/_persona.py` is its
# one home and does strictly more — it REGISTERS the module in `sys.modules` as
# `<persona>.server`, so repeated loads return one object instead of building a second; it pops
# a half-built module when `exec_module` raises; and it names the persona in the error when the
# file is absent.
#
# Checked before converting, because this is the shape that makes lumen's six files
# unconvertible: `_persona.load` is IDEMPOTENT, so a cached module would defeat any test that
# patches an env var and expects `server` to re-read it at import. This persona's `server.py`
# does read env at import — but no test here patches one, so nothing can collide.
from agience_chorus import _persona  # noqa: E402

ophan = _persona.load("server", __file__)


class _FakeResp:
    def __init__(self, payload, status=200):
        self._p = payload
        self.status_code = status
        self.text = json.dumps(payload) if isinstance(payload, (dict, list)) else str(payload)

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError("err", request=None, response=self)


class _FakeClient:
    def __init__(self, calls, *, email="jane@x.com", token="sys-jwt", invoke_status=200):
        self.calls = calls
        self._email = email
        self._token = token
        self._invoke_status = invoke_status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None, timeout=None):
        self.calls.append(("GET", url, None, headers))
        if "/internal/persons/" in url:
            return _FakeResp({"email": self._email} if self._email else {})
        raise AssertionError(f"unexpected GET {url}")

    async def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append(("POST", url, json, headers))
        if "/internal/system-delegation" in url:
            return _FakeResp({"token": self._token, "subject_id": "sp", "scope": "platform.email.send"})
        if "/op/invoke" in url:
            return _FakeResp({"status": "sent"}, status=self._invoke_status)
        raise AssertionError(f"unexpected POST {url}")


async def _platform_headers():
    return {"Authorization": "Bearer platform"}


@pytest.mark.asyncio
async def test_send_account_email_acts_as_system_principal(monkeypatch):
    calls: list = []
    monkeypatch.setattr(ophan, "_platform_email_operator_id", lambda: "op-123")
    monkeypatch.setattr(ophan, "_origin_headers", _platform_headers)
    monkeypatch.setattr(ophan.httpx, "AsyncClient", lambda *a, **k: _FakeClient(calls))

    await ophan._send_account_email("person-1", "Hi", "<p>x</p>")

    urls = [c[1] for c in calls]
    assert any("/internal/persons/person-1" in u for u in urls)      # recipient resolved
    assert any("/internal/system-delegation" in u for u in urls)     # system delegation obtained

    invoke = next(c for c in calls if "/op/invoke" in c[1])
    assert "op-123" in invoke[1]                                     # invoked the email operator
    assert invoke[3]["Authorization"] == "Bearer sys-jwt"           # as the system principal
    assert invoke[2]["params"]["to"] == "jane@x.com"                # delivered to the customer
    assert invoke[2]["params"]["subject"] == "Hi"


@pytest.mark.asyncio
async def test_send_account_email_skips_without_recipient(monkeypatch):
    calls: list = []
    monkeypatch.setattr(ophan, "_platform_email_operator_id", lambda: "op-123")
    monkeypatch.setattr(ophan, "_origin_headers", _platform_headers)
    monkeypatch.setattr(ophan.httpx, "AsyncClient", lambda *a, **k: _FakeClient(calls, email=""))

    await ophan._send_account_email("person-1", "Hi", "<p>x</p>")

    # No delegation requested and no operator invoke when there's no address.
    assert not any("/internal/system-delegation" in c[1] for c in calls)
    assert not any("/op/invoke" in c[1] for c in calls)


@pytest.mark.asyncio
async def test_send_account_email_is_best_effort(monkeypatch):
    """A failing send must not raise — the webhook/caller still succeeds."""
    monkeypatch.setattr(ophan, "_platform_email_operator_id", lambda: "op-123")
    monkeypatch.setattr(ophan, "_origin_headers", _platform_headers)
    monkeypatch.setattr(
        ophan.httpx, "AsyncClient",
        lambda *a, **k: _FakeClient([], invoke_status=500),
    )
    # Must not raise despite the 500 on op/invoke.
    await ophan._send_account_email("person-1", "Hi", "<p>x</p>")


@pytest.mark.asyncio
async def test_send_account_email_noop_without_person(monkeypatch):
    calls: list = []
    monkeypatch.setattr(ophan.httpx, "AsyncClient", lambda *a, **k: _FakeClient(calls))
    await ophan._send_account_email("", "Hi", "<p>x</p>")
    assert calls == []
