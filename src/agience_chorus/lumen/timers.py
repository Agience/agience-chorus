"""Timers — an operator that fires an artifact's operation on a schedule, on its owner's job grant.

A timer is a `vnd.agience.timer+json` card:

    context.timer = {
      "schedule": {"every_minutes": 15} | {"daily_at": "07:30"} | {"at": "2026-11-01T09:00:00Z"},
      "target":   {"artifact_id": "<id>", "operation": "invoke", "body": {...}},
      "results_to": "<container id>",         # optional: each run is recorded there as an artifact
      "inbox_to": "<container id>"            # optional: a failed run is raised there as an Inbox item
    }
    context.timer_state = {"last_run", "last_status", "last_error", "runs"}   # written by the operator

Nobody is signed in when a timer fires, so it runs on a job grant its owner makes at Origin when
they arm it (John, 2026-11-10): job `lumen.timer.<timer id>`, over the owner's own key, naming what
the timer reaches (`reach`, from `reach` below) and nothing else, approved at Origin's own page with
a step-up. Lumen keeps the grant's id, never a key. Each firing asks Origin, on Lumen's own key, for
two delegations under the grant (`POST /internal/job-delegation`): one narrowed to Lumen, exchanged
for Lumen's own server delegation, on which it reads and writes the timer, records the run and raises
an Inbox item; and one narrowed to Crystal, on which the target's operation runs. Both carry the
reach, every exchange from them keeps it, and Mantle holds each read and write to it and to what the
owner holds there. A revoked or expired grant mints nothing, and a firing refused its delegation
drops the timer; disarming forgets it here and revokes the grant at Origin's page.

Times are UTC.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

log = logging.getLogger("agience.lumen.timers")

TIMER_TYPE = "application/vnd.agience.timer+json"
#: How often due timers are looked for.
TICK_SECONDS = 30.0
#: How often a paused timer's card is read again, to see it resumed.
PAUSED_RECHECK = timedelta(minutes=15)
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


# ── the armed set ─────────────────────────────────────────────────────────────────────────────
class Store:
    """The timers armed on this node: `{timer_id: {"job_grant", "principal", "armed_at",
    "schedule", "last_run", "checked_at", "paused"}}`. The schedule and last run are the card's, as
    last read, so a pass asks Origin for a delegation only for a timer that is due."""

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

    def note(self, timer_id: str, **fields: Any) -> None:
        """Keep what a pass read of a timer still armed here."""
        with self._lock:
            data = self.load()
            if timer_id in data:
                data[timer_id].update(fields)
                self._save(data)

    def arm(self, timer_id: str, job_grant: str, principal: str,
            schedule: Optional[Dict[str, Any]] = None, last_run: Optional[str] = None) -> None:
        with self._lock:
            data = self.load()
            data[timer_id] = {"job_grant": job_grant, "principal": principal,
                              **({"schedule": schedule} if schedule else {}),
                              **({"last_run": last_run} if last_run else {}),
                              "armed_at": datetime.now(timezone.utc).isoformat()}
            self._save(data)

    def disarm(self, timer_id: str) -> Optional[Dict[str, Any]]:
        """Forget the timer; what it was armed with, or None when it was not armed here."""
        with self._lock:
            data = self.load()
            gone = data.pop(timer_id, None)
            if gone is not None:
                self._save(data)
            return gone


# ── what its key must reach ───────────────────────────────────────────────────────────────────
def reach(timer_id: str, spec: Dict[str, Any], workflow: Optional[Dict[str, Any]] = None,
          links: Optional[Dict[str, str]] = None, tools: Optional[List[tuple]] = None,
          platform: Optional[Dict[tuple, str]] = None) -> List[str]:
    """Every item a timer's grant must reach, in order, once each: the timer itself (its state is
    written back), its target, where it records runs and raises failures, and for a workflow each
    operator a step invokes and each artifact a step links. Never its workspace (BUG-035): the
    grant reaches what the timer runs and nothing beside it. A card made before steps were
    operators calls persona tools directly (`tools`, as (server, tool)); each one the platform
    offers as an operator (`platform`) needs that operator, so it is reached too. The owner approves
    this list at Origin, and Mantle holds the timer on each to what the owner holds there."""
    out: List[str] = []

    def add(rid: Any) -> None:
        if isinstance(rid, str) and rid and rid not in out:
            out.append(rid)

    add(timer_id)
    add((spec.get("target") or {}).get("artifact_id"))
    add(spec.get("results_to"))
    add(spec.get("inbox_to"))
    run = (workflow or {}).get("run") or {}
    if run.get("type") == "workflow":
        for step in run.get("steps") or []:
            add(step.get("operator_id"))
            for value in (step.get("arguments") or {}).values():
                if isinstance(value, str) and value.startswith("@link."):
                    add((links or {}).get(value[len("@link."):]))
    for pair in tools or []:
        add((platform or {}).get(tuple(pair)))
    return out


# ── firing ────────────────────────────────────────────────────────────────────────────────────
def step_failure(result: Any) -> Optional[str]:
    """Why an operation's result is a failure, or None. A tool result marked `isError`, or whose
    text is a JSON object carrying `error` (how Lumen's transforms and workflows report one), is a
    failure even when the gateway answered 200. 2026-10-18: a workflow whose step failed was
    reported as completed, and a timer recorded the run as a success."""
    if not isinstance(result, dict):
        return None
    blocks = result.get("content") or []
    text = blocks[0].get("text", "") if blocks and isinstance(blocks[0], dict) else ""
    if result.get("isError"):
        return text[:300] or "the tool reported an error"
    if text.lstrip().startswith("{"):
        try:
            payload = json.loads(text)
        except ValueError:
            return None
        if isinstance(payload, dict) and payload.get("error"):
            return str(payload["error"])[:300]
        # A tool result carried as the text of another (a Transform passes its tool's result on
        # whole): its own `isError` is the step's. 2026-10-19, on staging: a step naming a tool sage
        # does not have answered "Unknown tool" inside a result marked `isError: false`, and the
        # workflow and its timer recorded the run as a success.
        if isinstance(payload, dict) and isinstance(payload.get("content"), list):
            return step_failure(payload)
    return None


@dataclass
class Http:
    """The calls a firing makes, each with one of its delegations as its bearer. Injected for
    tests."""
    get: Callable[[str, str], Any]               # (url, token) -> (status, json)
    post: Callable[[str, str, dict], Any]        # (url, token, body) -> (status, json)
    patch: Callable[[str, str, dict], Any]       # (url, token, body) -> (status, json)


#: `(timer_id, armed entry) -> (status, for Mantle, for Crystal)`: a firing's two delegations from
#: Origin under the timer's job grant, or the status Origin refused them with.
Tokens = Callable[[str, Dict[str, Any]], Tuple[int, Optional[str], Optional[str]]]


def _context(doc: dict) -> dict:
    ctx = doc.get("context") or {}
    if isinstance(ctx, str):
        try:
            ctx = json.loads(ctx)
        except ValueError:
            ctx = {}
    return ctx if isinstance(ctx, dict) else {}


def fire_due(store: Store, http: Http, mantle: str, crystal: str, now: datetime,
             tokens: Tokens) -> Dict[str, str]:
    """One pass over the armed timers: fire each that is due. Returns {timer_id: what happened}."""
    report: Dict[str, str] = {}
    for timer_id, entry in sorted(store.load().items()):
        if not entry.get("job_grant"):
            # Armed on a key before timers ran on job grants: it is armed again to run.
            store.disarm(timer_id)
            report[timer_id] = "dropped (armed on a key; arm it again)"
            continue
        # Due by the card as last read, or nothing is asked of Origin.
        try:
            if entry.get("paused"):
                checked = entry.get("checked_at")
                if checked and now - _parse_time(checked) < PAUSED_RECHECK:
                    report[timer_id] = "paused"
                    continue
            elif entry.get("schedule") and not is_due(entry["schedule"], entry.get("last_run"), now):
                report[timer_id] = "not due"
                continue
        except (ScheduleError, ValueError):
            pass
        minted, key, run_key = tokens(timer_id, entry)
        if minted in (401, 403, 404):
            # Origin mints nothing under a revoked or expired grant: the timer is over.
            store.disarm(timer_id)
            report[timer_id] = f"dropped (grant {minted})"
            continue
        if minted != 200 or not key or not run_key:
            report[timer_id] = f"no delegation ({minted})"
            continue
        status, doc = http.get(f"{mantle}/artifacts/{timer_id}", key)
        if status in (401, 403, 404):
            # The card is gone, or out of the grant's reach: the timer is over.
            store.disarm(timer_id)
            report[timer_id] = f"dropped ({status})"
            continue
        if status != 200:
            report[timer_id] = f"timer unreadable ({status})"
            continue
        ctx = _context(doc)
        spec, state = ctx.get("timer") or {}, ctx.get("timer_state") or {}
        seen = {"schedule": spec.get("schedule"), "last_run": state.get("last_run"),
                "checked_at": now.isoformat(), "paused": spec.get("enabled") is False}
        if spec.get("enabled") is False:
            store.note(timer_id, **seen)
            report[timer_id] = "paused"
            continue
        try:
            if not is_due(spec.get("schedule"), state.get("last_run"), now):
                store.note(timer_id, **seen)
                report[timer_id] = "not due"
                continue
        except ScheduleError as exc:
            store.note(timer_id, **seen)
            report[timer_id] = f"bad schedule: {exc}"
            continue

        target = spec.get("target") or {}
        op = target.get("operation") or "invoke"
        code, result = http.post(f"{crystal}/artifacts/{target.get('artifact_id')}/op/{op}",
                                 run_key, target.get("body") or {})
        failure = step_failure(result) if 200 <= code < 300 else json.dumps(result)[:500]
        state = {**state, "last_run": now.isoformat(), "last_status": code, "runs": int(state.get("runs") or 0) + 1,
                 "last_ok": failure is None, "last_error": failure}
        http.patch(f"{mantle}/artifacts/{timer_id}", key,
                   {"context": json.dumps({**ctx, "timer_state": state})})
        store.note(timer_id, **{**seen, "last_run": state["last_run"]})
        if spec.get("results_to"):
            http.post(f"{mantle}/artifacts", key, {
                "container_id": spec["results_to"],
                "context": json.dumps({"title": f"{ctx.get('title') or 'Timer'} — {now:%Y-%m-%d %H:%M} UTC",
                                       "timer_id": timer_id, "status": code}),
                "content": json.dumps(result)[:RESULT_CHARS],
            })
        if failure is not None and spec.get("inbox_to"):
            # A failed run needs its owner: it is raised as an Inbox item where the owner said, and
            # approving it runs the target again, as the owner, once they have seen to the cause.
            from agience_chorus.lumen import inbox as _inbox
            title = ctx.get("title") or "Timer"
            http.post(f"{mantle}/artifacts", key, {
                "container_id": spec["inbox_to"], "content_type": _inbox.ITEM_TYPE,
                "context": json.dumps(_inbox.new_context(
                    f"{title} failed at {now:%Y-%m-%d %H:%M} UTC", failure,
                    evidence=[timer_id, str(target.get("artifact_id") or "")],
                    action={"artifact_id": target.get("artifact_id"), "operation": op,
                            "body": target.get("body") or {}} if target.get("artifact_id") else None,
                    source={"artifact_id": timer_id, "kind": "timer"}, by="timer",
                    at=now.isoformat())),
            })
        report[timer_id] = f"fired ({code})" if failure is None else f"fired ({code}), failed: {failure[:120]}"
    return report
