"""Timers — an operator that fires an artifact's operation on a schedule, or on a change, on its
owner's job grant.

A timer is a `vnd.agience.timer+json` card:

    context.timer = {
      "schedule": {"every_minutes": 15} | {"daily_at": "07:30"} | {"at": "2026-11-01T09:00:00Z"},
      # or, in its place, the changes it fires on:
      "on":       {"container_id": "<id>", "event_names": ["artifact.created"]},
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

A timer with `on` fires once for each change Mantle announces inside that container. Lumen listens
on Mantle's event stream on the timer's Lumen delegation, so it hears only what the grant reaches,
and keeps the stream's cursor, so a restart resumes where it stopped. The run's body gains
`params.artifact_id` (the artifact that changed) and `params.event` (what happened to it). A change
to the timer itself, or to what it records into `results_to` or raises into `inbox_to`, never fires
it.

Times are UTC.
"""
from __future__ import annotations

import asyncio
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
#: The changes a timer may fire on: Mantle's artifact events.
TRIGGER_EVENTS = ("artifact.created", "artifact.updated", "artifact.deleted")
#: How many event ids an armed trigger remembers, so an event delivered twice fires it once.
HEARD_KEPT = 200
#: How long a listener waits before it opens the stream again.
RETRY_SECONDS = 15.0


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


def check_on(on: Any) -> Dict[str, Any]:
    """The changes a timer fires on, validated: a `container_id` and `event_names` among
    `TRIGGER_EVENTS` (`artifact.created` when none are named)."""
    if not isinstance(on, dict):
        raise ScheduleError("on must be an object")
    container = on.get("container_id")
    if not isinstance(container, str) or not container.strip():
        raise ScheduleError("on names the container_id whose changes fire the timer")
    names = on.get("event_names") or ["artifact.created"]
    if isinstance(names, str):
        names = [names]
    if not isinstance(names, list) or any(n not in TRIGGER_EVENTS for n in names):
        raise ScheduleError(f"on.event_names are among {', '.join(TRIGGER_EVENTS)}")
    return {"container_id": container.strip(), "event_names": list(dict.fromkeys(names))}


def check_when(spec: Any) -> Tuple[str, Dict[str, Any]]:
    """When a timer fires: `("schedule", schedule)` or `("on", changes)`, exactly one of them."""
    spec = spec if isinstance(spec, dict) else {}
    named = [k for k in ("schedule", "on") if spec.get(k) not in (None, "", {})]
    if len(named) != 1:
        raise ScheduleError("a timer names exactly one of schedule or on")
    if named[0] == "schedule":
        return "schedule", check_schedule(spec["schedule"])
    return "on", check_on(spec["on"])


def is_due(schedule: Dict[str, Any], last_run: Optional[str], now: datetime) -> bool:
    """Is a run due at `now`, given the last one?"""
    s = check_schedule(schedule)
    last = _parse_time(last_run) if last_run else None
    if "every_minutes" in s:
        return last is None or now - last >= timedelta(minutes=s["every_minutes"])
    if "at" in s:
        # Once, at its time: again only if its time was moved past its last run (BUG-041,
        # 2026-11-10: a once-timer saved for a later time while armed never ran again).
        at = _parse_time(s["at"])
        return now >= at and (last is None or last < at)
    hh, mm = (int(x) for x in str(s["daily_at"]).split(":"))
    slot = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if now < slot:
        slot -= timedelta(days=1)
    return last is None or last < slot


# ── the armed set ─────────────────────────────────────────────────────────────────────────────
class Store:
    """The timers armed on this node: `{timer_id: {"job_grant", "principal", "armed_at",
    "schedule" | "on", "last_run", "checked_at", "paused", "since", "heard"}}`. The schedule, the
    changes and the last run are the card's, as last read, so a pass asks Origin for a delegation
    only for a timer that is due. `since` is the event stream's cursor a trigger resumes from, and
    `heard` the last event ids it fired on."""

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
            schedule: Optional[Dict[str, Any]] = None, last_run: Optional[str] = None,
            on: Optional[Dict[str, Any]] = None) -> None:
        with self._lock:
            data = self.load()
            data[timer_id] = {"job_grant": job_grant, "principal": principal,
                              **({"schedule": schedule} if schedule else {}),
                              **({"on": on} if on else {}),
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
    written back), its target, where it records runs and raises failures, the container whose
    changes fire it (what is inside is reached through it), and for a workflow each operator a step
    invokes and each artifact a step links. Never its workspace (BUG-035): the
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
    on = spec.get("on")
    add(on.get("container_id") if isinstance(on, dict) else None)
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


def _open(store: Store, http: Http, mantle: str, timer_id: str, entry: Dict[str, Any],
          tokens: Tokens) -> Tuple[Optional[str], Optional[str], Optional[str], dict]:
    """A firing's delegations and the timer's card read on them: `(None, key, run_key, card)`, or
    `(what happened, ...)` when it stops here. A refused grant or an unreadable card drops it."""
    minted, key, run_key = tokens(timer_id, entry)
    if minted in (401, 403, 404):
        # Origin mints nothing under a revoked or expired grant: the timer is over.
        store.disarm(timer_id)
        return f"dropped (grant {minted})", None, None, {}
    if minted != 200 or not key or not run_key:
        return f"no delegation ({minted})", None, None, {}
    status, doc = http.get(f"{mantle}/artifacts/{timer_id}", key)
    if status in (401, 403, 404):
        # The card is gone, or out of the grant's reach: the timer is over.
        store.disarm(timer_id)
        return f"dropped ({status})", None, None, {}
    if status != 200:
        return f"timer unreadable ({status})", None, None, {}
    return None, key, run_key, doc if isinstance(doc, dict) else {}


def _fire(http: Http, mantle: str, crystal: str, now: datetime, timer_id: str, key: str,
          run_key: str, ctx: dict, body: dict) -> Tuple[Dict[str, Any], str]:
    """Run the target's operation once with `body`, write the timer's state back, record the run
    and raise a failure. Returns the new state and what happened."""
    spec, state = ctx.get("timer") or {}, ctx.get("timer_state") or {}
    target = spec.get("target") or {}
    op = target.get("operation") or "invoke"
    code, result = http.post(f"{crystal}/artifacts/{target.get('artifact_id')}/op/{op}",
                             run_key, body)
    failure = step_failure(result) if 200 <= code < 300 else json.dumps(result)[:500]
    state = {**state, "last_run": now.isoformat(), "last_status": code,
             "runs": int(state.get("runs") or 0) + 1, "last_ok": failure is None,
             "last_error": failure}
    http.patch(f"{mantle}/artifacts/{timer_id}", key,
               {"context": json.dumps({**ctx, "timer_state": state})})
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
                        "body": body} if target.get("artifact_id") else None,
                source={"artifact_id": timer_id, "kind": "timer"}, by="timer",
                at=now.isoformat())),
        })
    return state, (f"fired ({code})" if failure is None else f"fired ({code}), failed: {failure[:120]}")


def fire_due(store: Store, http: Http, mantle: str, crystal: str, now: datetime,
             tokens: Tokens) -> Dict[str, str]:
    """One pass over the armed timers: fire each that is due. Returns {timer_id: what happened}.
    A timer that fires on changes is left to its listener (`listen`)."""
    report: Dict[str, str] = {}
    for timer_id, entry in sorted(store.load().items()):
        if not entry.get("job_grant"):
            # Armed on a key before timers ran on job grants: it is armed again to run.
            store.disarm(timer_id)
            report[timer_id] = "dropped (armed on a key; arm it again)"
            continue
        if entry.get("on"):
            report[timer_id] = "listening"
            continue
        # Due by the card as last read, or nothing is asked of Origin.
        try:
            if entry.get("paused"):
                checked = entry.get("checked_at")
                if checked and now - _parse_time(checked) < PAUSED_RECHECK:
                    report[timer_id] = "paused"
                    continue
            elif entry.get("schedule") and not is_due(entry["schedule"], entry.get("last_run"), now):
                # The card is read again now and then, so a schedule saved while armed is taken
                # up (BUG-041: one saved after arming was never seen).
                checked = entry.get("checked_at") or entry.get("armed_at")
                if not checked or now - _parse_time(checked) < PAUSED_RECHECK:
                    report[timer_id] = "not due"
                    continue
        except (ScheduleError, ValueError):
            pass
        stop, key, run_key, doc = _open(store, http, mantle, timer_id, entry, tokens)
        if stop:
            report[timer_id] = stop
            continue
        ctx = _context(doc)
        spec, state = ctx.get("timer") or {}, ctx.get("timer_state") or {}
        seen = {"schedule": spec.get("schedule"), "last_run": state.get("last_run"),
                "checked_at": now.isoformat(), "paused": spec.get("enabled") is False}
        if spec.get("on") and not spec.get("schedule"):
            # Saved to fire on changes while armed: its listener takes it from here.
            try:
                store.note(timer_id, **seen, on=check_on(spec["on"]))
                report[timer_id] = "listening"
            except ScheduleError as exc:
                store.note(timer_id, **seen)
                report[timer_id] = f"bad trigger: {exc}"
            continue
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
        state, report[timer_id] = _fire(http, mantle, crystal, now, timer_id, key, run_key, ctx,
                                        (spec.get("target") or {}).get("body") or {})
        store.note(timer_id, **{**seen, "last_run": state["last_run"]})
    return report


# ── firing on changes ─────────────────────────────────────────────────────────────────────────
def advance(since: Any, cursor: Any) -> str:
    """The stream position `since` moved on to an event's `cursor` (`origin:seq,...`): each origin
    at the later of the two."""
    marks: Dict[str, int] = {}
    for text in (since, cursor):
        for part in str(text or "").split(","):
            origin, _, seq = part.strip().rpartition(":")
            if origin and seq.isdigit():
                marks[origin] = max(marks.get(origin, 0), int(seq))
    return ",".join(f"{o}:{n}" for o, n in sorted(marks.items()))


def passes_over(event: Dict[str, Any], timer_id: str, spec: Dict[str, Any]) -> Optional[str]:
    """Why an event does not fire the timer, or None when it does. The stream already selects the
    container and event names it was opened on; the card, as read now, decides."""
    on = check_on(spec.get("on"))
    if event.get("event") not in on["event_names"]:
        return "not an event it fires on"
    art = (event.get("payload") or {}).get("artifact") or {}
    if str(art.get("id") or "") == timer_id:
        return "its own card"
    home = art.get("collection_id")
    if home and home in (spec.get("results_to"), spec.get("inbox_to")):
        return "its own record"
    return None


def fire_on_event(store: Store, http: Http, mantle: str, crystal: str, now: datetime,
                  tokens: Tokens, timer_id: str, event: Dict[str, Any]) -> str:
    """Fire a timer once for one event its stream delivered. Returns what happened."""
    entry = store.load().get(timer_id)
    if not entry or not entry.get("on"):
        return "not listening"
    event_id = str(event.get("event_id") or "")
    heard = list(entry.get("heard") or [])
    if event_id and event_id in heard:
        return "already heard"
    stop, key, run_key, doc = _open(store, http, mantle, timer_id, entry, tokens)
    if stop:
        return stop
    ctx = _context(doc)
    spec, state = ctx.get("timer") or {}, ctx.get("timer_state") or {}
    seen = {"last_run": state.get("last_run"), "checked_at": now.isoformat(),
            "paused": spec.get("enabled") is False,
            "since": advance(entry.get("since"), event.get("cursor")),
            "heard": (heard + [event_id])[-HEARD_KEPT:] if event_id else heard}
    if not spec.get("on"):
        # Saved to a schedule while armed: the pass over due timers takes it from here.
        store.note(timer_id, **seen, on=None, schedule=spec.get("schedule"))
        return "no longer listening"
    try:
        on = check_on(spec["on"])
        why = passes_over(event, timer_id, spec)
    except ScheduleError as exc:
        store.note(timer_id, **seen)
        return f"bad trigger: {exc}"
    if spec.get("enabled") is False:
        store.note(timer_id, **seen, on=on)
        return "paused"
    if why:
        store.note(timer_id, **seen, on=on)
        return f"passed over ({why})"
    body = dict((spec.get("target") or {}).get("body") or {})
    art = (event.get("payload") or {}).get("artifact") or {}
    body["params"] = {**(body.get("params") or {}), "artifact_id": str(art.get("id") or ""),
                      "event": str(event.get("event") or "")}
    state, what = _fire(http, mantle, crystal, now, timer_id, key, run_key, ctx, body)
    store.note(timer_id, **{**seen, "on": on, "last_run": state["last_run"]})
    return what


#: `(url, token) -> async context manager` yielding a socket with `async send(text)` and
#: `async recv() -> text`. Injected for tests.
Connect = Callable[[str, str], Any]


async def listen(store: Store, timer_id: str, tokens: Tokens, connect: Connect, events_url: str,
                 fire: Callable[[Dict[str, Any]], str], retry: float = RETRY_SECONDS) -> str:
    """Hear the changes an armed timer fires on, for as long as it stays armed to them: open
    Mantle's event stream on the timer's Lumen delegation, subscribed to its container and event
    names from the cursor last kept, and `fire` each event delivered. The stream is opened again
    when it closes (a delegation outlives its socket only so long). Returns why it stopped: the
    timer was disarmed, its grant refused, or its card no longer names these changes."""
    while True:
        entry = store.load().get(timer_id)
        if not entry or not entry.get("on"):
            return "not listening"
        on = entry["on"]
        minted, key, _ = await asyncio.to_thread(tokens, timer_id, entry)
        if minted in (401, 403, 404):
            store.disarm(timer_id)
            return f"dropped (grant {minted})"
        if minted == 200 and key:
            try:
                async with connect(events_url, key) as ws:
                    await ws.send(json.dumps({
                        "op": "subscribe", "id": timer_id,
                        "filter": {"container_id": on["container_id"],
                                   "event_names": list(on["event_names"])},
                        "since": entry.get("since") or ""}))
                    while True:
                        msg = json.loads(await ws.recv())
                        if not isinstance(msg, dict):
                            continue
                        if msg.get("error"):
                            log.warning("timer %s: the event stream refused: %s", timer_id,
                                        str(msg["error"])[:200])
                            break
                        if "event" in msg:
                            what = await asyncio.to_thread(fire, msg)
                            log.info("timer %s on %s: %s", timer_id, msg.get("event"), what)
                        held = store.load().get(timer_id)
                        if not held or held.get("on") != on:
                            break
            except asyncio.CancelledError:
                raise
            except Exception as exc:                                  # noqa: BLE001
                log.info("timer %s: the event stream closed (%s)", timer_id, type(exc).__name__)
        held = store.load().get(timer_id)
        if not held or not held.get("on"):
            return "not listening"
        if held.get("on") != on:
            continue
        await asyncio.sleep(retry)
