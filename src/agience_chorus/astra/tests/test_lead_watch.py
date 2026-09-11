"""The lead watcher: off unless asked, scoped to one container, and reading with the right key.

⛔ THE FIRST TEST IS THE ONE THAT MATTERS. This subscribes to the store's change feed from inside
the chorus host, and chorus runs on more than one box. A watcher that started itself would handle
the same lead once per host — duplicate notifications from a component nobody switched on. So it
is off unless `LEADS_WATCH_ENABLED` says otherwise, and that is pinned here rather than left to
the default in `os.getenv`.

The rest pin the properties that keep it from doing damage: it refuses to run half-configured, it
ignores artifacts outside its container, and it reads with the CONTAINER's grant key rather than
astra's service identity — which cannot read a lead at all.
"""
from __future__ import annotations

import asyncio

import pytest

from agience_chorus.astra import lead_watch


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("LEADS_WATCH_ENABLED", "LEADS_COLLECTION_ID", "LEADS_GRANT_KEY", "MANTLE_URI"):
        monkeypatch.delenv(name, raising=False)


def test_it_is_off_unless_enabled(monkeypatch):
    """⛔ THE REGRESSION THIS PREVENTS: a watcher nobody switched on, running on every host.

    ⚠ EVERYTHING ELSE IS CONFIGURED HERE ON PURPOSE. An earlier version left the container and key
    unset, so `start()` returned None because it was UNCONFIGURED — and the test passed
    identically with the flag forced to True. It proved nothing about the flag. The flag is now
    the only reason this can return None.
    """
    monkeypatch.setenv("LEADS_COLLECTION_ID", "container-A")
    monkeypatch.setenv("LEADS_GRANT_KEY", "a-key")
    assert lead_watch._enabled() is False
    assert lead_watch.start() is None


@pytest.mark.parametrize("flag", ["1", "true", "yes", "on", "TRUE"])
def test_the_flag_is_read_permissively(monkeypatch, flag):
    monkeypatch.setenv("LEADS_WATCH_ENABLED", flag)
    assert lead_watch._enabled() is True


def test_enabled_but_unconfigured_refuses_to_start(monkeypatch, caplog):
    """Subscribed with no container to filter on, it would read every artifact it could see; with
    no key it would warn once per event. Neither is a useful state to run in."""
    monkeypatch.setenv("LEADS_WATCH_ENABLED", "1")
    assert lead_watch.start() is None
    assert any("not configured" in r.getMessage() for r in caplog.records)


def test_it_only_reacts_to_its_own_container(monkeypatch):
    monkeypatch.setenv("LEADS_COLLECTION_ID", "container-A")
    assert lead_watch._is_ours({"collection_id": "container-A"}) is True
    assert lead_watch._is_ours({"collection_id": "container-B"}) is False
    assert lead_watch._is_ours({}) is False


def test_with_no_container_configured_nothing_is_ours(monkeypatch):
    """Guard on the guard: an empty container id must not match an artifact with no collection,
    which would make every top-level artifact 'ours'."""
    assert lead_watch._is_ours({"collection_id": ""}) is False
    assert lead_watch._is_ours({}) is False


def test_the_read_uses_the_grant_key_not_the_service_identity(monkeypatch):
    """⛔ THE CREDENTIAL MATTERS. astra's service token can subscribe to the feed but cannot read
    a lead — measured: it answers 404. Reading with the wrong one fails in a way that looks like
    a missing artifact."""
    monkeypatch.setenv("LEADS_GRANT_KEY", "the-container-key")
    monkeypatch.setenv("MANTLE_URI", "http://mantle.test")
    seen = {}

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"id": "a1", "content": "a lead"}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            seen["url"] = url
            seen["auth"] = (headers or {}).get("Authorization")
            return _Resp()

    monkeypatch.setattr(lead_watch.httpx, "AsyncClient", _Client)
    doc = asyncio.run(lead_watch._read_artifact("a1"))
    assert doc == {"id": "a1", "content": "a lead"}
    assert seen["auth"] == "Bearer the-container-key"
    assert seen["url"] == "http://mantle.test/artifacts/a1"


def test_no_key_means_no_read(monkeypatch):
    """Without the key it must not fall back to any other credential."""
    monkeypatch.setenv("MANTLE_URI", "http://mantle.test")
    assert asyncio.run(lead_watch._read_artifact("a1")) is None


def test_ws_url_derives_from_the_mantle_uri(monkeypatch):
    monkeypatch.setenv("MANTLE_URI", "https://mantle.agience.ai")
    assert lead_watch._ws_url() == "wss://mantle.agience.ai/events"
    monkeypatch.setenv("MANTLE_URI", "http://127.0.0.1:8084")
    assert lead_watch._ws_url() == "ws://127.0.0.1:8084/events"


def test_notify_does_not_claim_to_have_sent(caplog):
    """The sending identity is unresolved: chorus holds no read on the platform email credentials.
    Saying so is the correct behaviour — a notify that silently did nothing would read as a lead
    that was handled."""
    import logging

    with caplog.at_level(logging.INFO, logger=lead_watch.log.name):
        asyncio.run(lead_watch.notify("a1", {"content": "x"}))
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "deferred" in msg
    assert "sent" not in msg.lower().replace("presented", "")


def test_astra_defines_exactly_one_server_startup():
    """⛔ A SECOND DEFINITION SILENTLY REPLACES THE FIRST.

    `personas.PersonaBinding` takes `getattr(mod, "server_startup", None)` — one attribute, last
    definition wins. Appending a new `server_startup` to add the watcher shadowed the original and
    `await _auth.startup()` stopped running: the host booted, astra mounted, and its authentication
    was never initialised. Nothing in the boot log said so.
    """
    import pathlib

    src = pathlib.Path(lead_watch.__file__).with_name("server.py").read_text(encoding="utf-8")
    assert src.count("async def server_startup") == 1, (
        "astra defines server_startup more than once; the later one wins and the earlier one — "
        "including _auth.startup() — never runs"
    )


def test_the_startup_hook_still_initialises_auth():
    """The watcher must be additive. If the hook stops awaiting the auth startup, the persona
    mounts unauthenticated."""
    import inspect

    from agience_chorus.astra import server as astra_server

    body = inspect.getsource(astra_server.server_startup)
    assert "_auth.startup()" in body
    assert "lead_watch" in body
