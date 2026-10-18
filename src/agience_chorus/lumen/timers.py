"""Timers — an operator that fires an artifact's operation on a schedule, on a key its owner issued.

A timer is a `vnd.agience.timer+json` card:

    context.timer = {
      "schedule": {"every_minutes": 15} | {"daily_at": "07:30"} | {"at": "2026-11-01T09:00:00Z"},
      "target":   {"artifact_id": "<id>", "operation": "invoke", "body": {...}},
      "results_to": "<container id>"          # optional: each run is recorded there as an artifact
    }
    context.timer_state = {"last_run", "last_status", "last_error", "runs"}   # written by the operator

Nobody is signed in when a timer fires, so it acts on a grant: a key the owner issues from the card
when they arm it (`POST /grants/keys`, over the timer's workspace). The key reaches what the owner
gave it and nothing else; every read and write a firing makes — the timer card, the target's
operation through Crystal, a workflow's steps on other personas — is decided by Mantle against that
one grant. Revoking the key, or disarming the card (which revokes it), stops the timer: a firing
whose key is refused drops the timer.

The key reaches this operator from the app's host, never through the card's view, and is kept only
sealed: RSA-OAEP under this node's chorus key (`KEYS_DIR/chorus.public.pem`), so the file holds
nothing a reader of the disk can use.

Times are UTC.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

log = logging.getLogger("agience.lumen.timers")

TIMER_TYPE = "application/vnd.agience.timer+json"
#: How often due timers are looked for.
TICK_SECONDS = 30.0
#: The most a run's result recorded into `results_to` carries.
RESULT_CHARS = 4000


# ── schedules ─────────────────────────────────────────────────────────────────────────────────
class ScheduleError(ValueError):
    """The schedule cannot be read. The message names why."""


def _parse_time(value: str) -> datetime:
    t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def check_schedule(schedule: Any) -> Dict[str, Any]:
    """The schedule, validated: exactly one of `every_minutes` (>= 1), `daily_at` ("HH:MM"), `at`."""
    if not isinstance(schedule, dict):
        raise ScheduleError("schedule must be an object")
    kinds = [k for k in ("every_minutes", "daily_at", "at") if schedule.get(k) not in (None, "")]
    if len(kinds) != 1:
        raise ScheduleError("schedule names exactly one of every_minutes, daily_at, at")
    kind = kinds[0]
    if kind == "every_minutes":
        n = schedule["every_minutes"]
        if not isinstance(n, int) or isinstance(n, bool) or n < 1:
            raise ScheduleError("every_minutes is a whole number of minutes, at least 1")
    elif kind == "daily_at":
        try:
            hh, mm = str(schedule["daily_at"]).split(":")
            if not (0 <= int(hh) < 24 and 0 <= int(mm) < 60):
                raise ValueError
        except ValueError:
            raise ScheduleError("daily_at is HH:MM, 24-hour, UTC")
    else:
        try:
            _parse_time(schedule["at"])
        except ValueError:
            raise ScheduleError("at is an ISO 8601 time")
    return {kind: schedule[kind]}


def is_due(schedule: Dict[str, Any], last_run: Optional[str], now: datetime) -> bool:
    """Is a run due at `now`, given the last one?"""
    s = check_schedule(schedule)
    last = _parse_time(last_run) if last_run else None
    if "every_minutes" in s:
        return last is None or now - last >= timedelta(minutes=s["every_minutes"])
    if "at" in s:
        return last is None and now >= _parse_time(s["at"])
    hh, mm = (int(x) for x in str(s["daily_at"]).split(":"))
    slot = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if now < slot:
        slot -= timedelta(days=1)
    return last is None or last < slot


# ── sealing ───────────────────────────────────────────────────────────────────────────────────
def _keys_dir() -> Path:
    return Path(os.environ.get("KEYS_DIR") or ".")


def seal(secret: str, keys_dir: Optional[Path] = None) -> str:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    pub = serialization.load_pem_public_key(((keys_dir or _keys_dir()) / "chorus.public.pem").read_bytes())
    sealed = pub.encrypt(secret.encode(), padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),
                                                        algorithm=hashes.SHA256(), label=None))
    return base64.b64encode(sealed).decode()


def unseal(sealed: str, keys_dir: Optional[Path] = None) -> str:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    key = serialization.load_pem_private_key(((keys_dir or _keys_dir()) / "chorus.private.pem").read_bytes(),
                                             password=None)
    return key.decrypt(base64.b64decode(sealed), padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),
                                                               algorithm=hashes.SHA256(), label=None)).decode()


# ── the armed set ─────────────────────────────────────────────────────────────────────────────
class Store:
    """The timers armed on this node: `{timer_id: {"sealed_key", "key_id", "armed_at"}}`."""

    def __init__(self, directory: Path):
        self.path = Path(directory) / "armed.json"
        self._lock = threading.Lock()

    def load(self) -> Dict[str, Dict[str, str]]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self, data: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".next")
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, self.path)

    def arm(self, timer_id: str, sealed_key: str, key_id: str) -> None:
        with self._lock:
            data = self.load()
            data[timer_id] = {"sealed_key": sealed_key, "key_id": key_id,
                              "armed_at": datetime.now(timezone.utc).isoformat()}
            self._save(data)

    def disarm(self, timer_id: str) -> bool:
        with self._lock:
            data = self.load()
            gone = data.pop(timer_id, None) is not None
            if gone:
                self._save(data)
            return gone


# ── firing ────────────────────────────────────────────────────────────────────────────────────
@dataclass
class Http:
    """The calls a firing makes, each with the timer's key as its bearer. Injected for tests."""
    get: Callable[[str, str], Any]               # (url, key) -> (status, json)
    post: Callable[[str, str, dict], Any]        # (url, key, body) -> (status, json)
    patch: Callable[[str, str, dict], Any]       # (url, key, body) -> (status, json)


def _context(doc: dict) -> dict:
    ctx = doc.get("context") or {}
    if isinstance(ctx, str):
        try:
            ctx = json.loads(ctx)
        except ValueError:
            ctx = {}
    return ctx if isinstance(ctx, dict) else {}


def fire_due(store: Store, http: Http, mantle: str, crystal: str, now: datetime,
             unseal_fn: Callable[[str], str] = unseal) -> Dict[str, str]:
    """One pass over the armed timers: fire each that is due. Returns {timer_id: what happened}."""
    report: Dict[str, str] = {}
    for timer_id, entry in sorted(store.load().items()):
        try:
            key = unseal_fn(entry["sealed_key"])
        except Exception as exc:
            report[timer_id] = f"unsealable ({type(exc).__name__})"
            continue
        status, doc = http.get(f"{mantle}/artifacts/{timer_id}", key)
        if status in (401, 403, 404):
            # The key was revoked, or the card is gone or out of its reach: the timer is over.
            store.disarm(timer_id)
            report[timer_id] = f"dropped ({status})"
            continue
        if status != 200:
            report[timer_id] = f"timer unreadable ({status})"
            continue
        ctx = _context(doc)
        spec, state = ctx.get("timer") or {}, ctx.get("timer_state") or {}
        if spec.get("enabled") is False:
            report[timer_id] = "paused"
            continue
        try:
            if not is_due(spec.get("schedule"), state.get("last_run"), now):
                report[timer_id] = "not due"
                continue
        except ScheduleError as exc:
            report[timer_id] = f"bad schedule: {exc}"
            continue

        target = spec.get("target") or {}
        op = target.get("operation") or "invoke"
        code, result = http.post(f"{crystal}/artifacts/{target.get('artifact_id')}/op/{op}", key,
                                 target.get("body") or {})
        ok = 200 <= code < 300
        state = {**state, "last_run": now.isoformat(), "last_status": code, "runs": int(state.get("runs") or 0) + 1,
                 "last_error": None if ok else json.dumps(result)[:500]}
        http.patch(f"{mantle}/artifacts/{timer_id}", key,
                   {"context": json.dumps({**ctx, "timer_state": state})})
        if spec.get("results_to"):
            http.post(f"{mantle}/artifacts", key, {
                "container_id": spec["results_to"],
                "context": json.dumps({"title": f"{ctx.get('title') or 'Timer'} — {now:%Y-%m-%d %H:%M} UTC",
                                       "timer_id": timer_id, "status": code}),
                "content": json.dumps(result)[:RESULT_CHARS],
            })
        report[timer_id] = f"fired ({code})"
    return report
