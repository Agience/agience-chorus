"""Astra watches the lattice for inbound artifacts and reacts to them.

An artifact arriving in a watched container is an INGESTION event, which is why this lives in
astra rather than in the store: Mantle emits the change, a tekton subscribes, and the workflow
happens in the tekton. Mantle initiates nothing outbound — `services/peer_signing` refuses to sign
for a direction it never initiates, and that stays true.

HOW IT SEES THE LEADS, AND WHY IT IS NOT A SYSTEM CONSUMER
----------------------------------------------------------
`_SYSTEM_EVENT_CONSUMERS` in mantle holds `{"crystal"}` and is documented as "a standing exception
to README invariant #2 ... keep this list tight". This does not join it. Instead the container
carries an ordinary grant and this holds the key to it:

    depositor  →  add/write on the container   (a lead can be dropped in without reading any)
    astra      →  READ on the container        (so it sees everything inside)

⛔ THE KEY IS A GRANT KEY, NOT A GRANT ON THE SERVICE PRINCIPAL. Measured 2026-09-11: granting
`grantee_type=service, grantee_id=chorus` returns **201** and is **inert** — `check_access` serves
"a user's [grants] ... looked up by user_id, a grant key's [already resolved]", and a service
principal has no `user_id`, so that row is never consulted and every read still answers 404.
`effective_flags` even reports `can_read` for it, so the grant service and the read path disagree
about that row. A grant key holds no `user_id` by design, is scoped to the one container, and is
revocable without touching an account.

OFF BY DEFAULT
--------------
`LEADS_WATCH_ENABLED` must be set. A watcher that starts itself on every node would subscribe from
every host that happens to run chorus, and the same lead would be handled once per host.

It never raises into the host: the task is created detached, every exception is caught, and a
failure to reach the feed becomes a retry rather than a boot failure.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Optional

import httpx

log = logging.getLogger("agience-server-astra.lead_watch")

#: The events worth waking for. Matches crystal's own set — an artifact is created, or updated.
_CHANGE_EVENTS = ("artifact.created", "artifact.updated")

#: Backoff bounds for reconnecting to the feed. The store restarting is normal; a watcher that
#: gave up on the first disconnect would need a chorus restart to resume.
_BACKOFF_START = 2.0
_BACKOFF_MAX = 60.0


def _enabled() -> bool:
    return (os.getenv("LEADS_WATCH_ENABLED", "") or "").strip().lower() in ("1", "true", "yes", "on")


def _container() -> str:
    return (os.getenv("LEADS_COLLECTION_ID", "") or "").strip()


def _grant_key() -> str:
    return (os.getenv("LEADS_GRANT_KEY", "") or "").strip()


def _mantle_uri() -> str:
    return (os.getenv("MANTLE_URI", "http://localhost:8081") or "").rstrip("/")


def _ws_url() -> str:
    base = _mantle_uri()
    if base.startswith("https://"):
        return "wss://" + base[len("https://"):] + "/events"
    if base.startswith("http://"):
        return "ws://" + base[len("http://"):] + "/events"
    return base + "/events"


async def _read_artifact(artifact_id: str) -> Optional[dict]:
    """Read the artifact with the CONTAINER's grant key, not with astra's service identity.

    The service identity can subscribe to the feed but cannot read a lead — that is the whole
    reason the key exists. Using the wrong credential here fails as a 404, which reads as "the
    artifact is gone" rather than "I asked as the wrong principal".
    """
    key = _grant_key()
    if not key:
        return None
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(f"{_mantle_uri()}/artifacts/{artifact_id}",
                             headers={"Authorization": f"Bearer {key}"})
    if r.status_code != 200:
        log.warning("lead_watch: artifact %s unreadable with the container key (HTTP %s)",
                    artifact_id, r.status_code)
        return None
    return r.json()


async def _handle(artifact: dict) -> None:
    """React to one inbound artifact. Reads it, then hands it to the notification step."""
    artifact_id = str(artifact.get("id") or artifact.get("root_id") or "")
    doc = await _read_artifact(artifact_id)
    if doc is None:
        return

    content = doc.get("content")
    size = len(content) if isinstance(content, str) else 0
    log.info("lead_watch: inbound %s (%s, %d chars) in container %s",
             artifact_id, doc.get("content_type"), size, _container())

    await notify(artifact_id, doc)


async def notify(artifact_id: str, doc: dict) -> None:
    """Hand the inbound artifact to the operator notification.

    ⚠ DELIBERATELY SEPARATE, AND CURRENTLY UNRESOLVED. `iris:send_email` resolves the Gmail
    credentials under the CALLER's delegation, and the principals that hold `can_read` on them are
    the platform operator and the platform system principal — not chorus. A call from here would
    reach `send_email` and fail on the authorizer read, which is the isolation working rather than
    a bug to route around.

    So this records the intent and says precisely what is missing, instead of pretending. When the
    sending identity is settled, this is the one function that changes.
    """
    log.info(
        "lead_watch: notification deferred for %s — chorus holds no read on the platform email "
        "credentials (operator and system principal do). Resolve the sending identity to enable.",
        artifact_id,
    )


def _is_ours(artifact: dict) -> bool:
    """Only artifacts inside the watched container."""
    want = _container()
    return bool(want) and str(artifact.get("collection_id") or "") == want


async def _session(token_fn) -> None:
    import websockets

    url = _ws_url()
    async with websockets.connect(
        url, additional_headers={"Authorization": f"Bearer {token_fn()}"}
    ) as ws:
        await ws.send(json.dumps({
            "op": "subscribe", "id": "astra-lead-watch",
            "filter": {"event_names": list(_CHANGE_EVENTS)},
        }))
        log.info("lead_watch: subscribed at %s for container %s", url, _container())
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            if msg.get("event") not in _CHANGE_EVENTS:
                continue
            payload = msg.get("payload") or {}
            art = payload.get("artifact") if isinstance(payload.get("artifact"), dict) else payload
            if not isinstance(art, dict) or not _is_ours(art):
                continue
            try:
                await _handle(art)
            except Exception:
                # One bad artifact must not end the subscription; the next event still arrives.
                log.warning("lead_watch: handling failed for %s",
                            art.get("id"), exc_info=True)


async def run() -> None:
    """The watch loop. Reconnects with backoff; never raises.

    ⛔ THE FEED IS SUBSCRIBED WITH THE GRANT KEY, NOT WITH ASTRA'S SERVICE TOKEN, and the
    difference is invisible at connect time. Measured 2026-09-11, both connected and both were
    acked; an artifact was then created in the watched container:

        [service]  subscribed -> received NOTHING
        [grantkey] subscribed -> EVENT artifact.created id=ae274f1d collection=b1fefeae

    Mantle delivers the change feed per-ACL — that is exactly why `_SYSTEM_EVENT_CONSUMERS` exists
    for crystal — and a service principal holds no grant on the container, so it is told nothing.
    The failure mode is the worst kind: a healthy connection, a successful subscribe, and silence
    forever.

    One credential, one scope: the key that can READ the container is the key that SEES its
    events. Nothing here needs astra's service identity at all.
    """
    def token_fn() -> str:
        return _grant_key()

    delay = _BACKOFF_START
    while True:
        try:
            await _session(token_fn)
            delay = _BACKOFF_START            # a clean end means the feed closed; reconnect fast
        except asyncio.CancelledError:
            log.info("lead_watch: stopped")
            raise
        except Exception as exc:  # noqa: BLE001 — any failure is a retry, never a crash
            log.warning("lead_watch: session ended (%s: %s); retrying in %.0fs",
                        type(exc).__name__, exc, delay)
        await asyncio.sleep(delay)
        delay = min(delay * 1.5, _BACKOFF_MAX)


def start() -> Optional[Any]:
    """Start the watcher if it is configured. Returns the task, or None when it is off.

    Refuses to start half-configured: a watcher subscribed to the feed with no container to filter
    on would read every artifact it could, and one with no key would log an unreadable warning for
    every event on the node.
    """
    if not _enabled():
        return None
    missing = [n for n, v in (("LEADS_COLLECTION_ID", _container()),
                              ("LEADS_GRANT_KEY", _grant_key())) if not v]
    if missing:
        log.warning("lead_watch: enabled but not configured (%s) — not starting", ", ".join(missing))
        return None
    log.info("lead_watch: starting for container %s", _container())
    return asyncio.create_task(run())
