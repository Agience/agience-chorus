"""Inbox items — what needs a person: an outlier, a failed routine, a draft to approve.

An item is a `vnd.agience.inbox-item+json` card, placed in a person's Inbox (or any container the
raiser can write to):

    context.item = {
      "state":    "new" | "triaged" | "resolved",
      "reason":   "<why it needs a person>",
      "evidence": ["<artifact id>", ...],                 # what it came from
      "action":   {"artifact_id", "operation", "body"},   # optional: what approving runs
      "source":   {"artifact_id", "kind"},                # optional: what raised it (a timer, a step)
      "history":  [{"state", "at", "by", "note"?}, ...],  # each move, oldest first
      "outcome":  {...}                                    # written when an approval runs
    }

Whoever raises an item does so on their own credential (a person, or a key a timer acts on), so an
item appears only where its raiser may write. Approving runs the action on the APPROVER's
credential: approval is the person doing it, which is why the view shows the action before it runs.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

ITEM_TYPE = "application/vnd.agience.inbox-item+json"
STATES = ("new", "triaged", "resolved")
#: Each state's next states. A resolved item can be reopened; nothing goes back to triaged from new's
#: past, so the history reads forward.
MOVES: Dict[str, tuple] = {
    "new": ("triaged", "resolved"),
    "triaged": ("resolved", "new"),
    "resolved": ("new",),
}
#: The most an approval's result recorded on the item carries.
OUTCOME_CHARS = 2000


class ItemError(ValueError):
    """The item, or the move asked of it, cannot be made. The message names why."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def check_action(action: Any) -> Optional[Dict[str, Any]]:
    """An action as stored, or None for no action. Refuses one that names no artifact."""
    if action in (None, {}, ""):
        return None
    if not isinstance(action, dict) or not str(action.get("artifact_id") or "").strip():
        raise ItemError("an action names the artifact whose operation approving runs (artifact_id)")
    body = action.get("body")
    body = {} if body is None else body
    if not isinstance(body, dict):
        raise ItemError("an action's body is an object")
    return {"artifact_id": str(action["artifact_id"]).strip(),
            "operation": str(action.get("operation") or "invoke").strip() or "invoke",
            "body": body}


def new_context(title: str, reason: str, evidence: Optional[List[str]] = None,
                action: Any = None, source: Optional[Dict[str, Any]] = None,
                by: str = "", at: Optional[str] = None) -> Dict[str, Any]:
    """The context of a newly raised item."""
    if not str(title or "").strip():
        raise ItemError("an item has a title")
    if not str(reason or "").strip():
        raise ItemError("an item says why it needs a person (reason)")
    item: Dict[str, Any] = {
        "state": "new",
        "reason": str(reason).strip(),
        "evidence": [str(e) for e in (evidence or []) if str(e).strip()],
        "history": [{"state": "new", "at": at or _now(), "by": by}],
    }
    checked = check_action(action)
    if checked:
        item["action"] = checked
    if source:
        item["source"] = {k: v for k, v in source.items() if k in ("artifact_id", "kind")}
    return {"title": str(title).strip(), "content_type": ITEM_TYPE, "item": item}


def item_of(ctx: Dict[str, Any]) -> Dict[str, Any]:
    item = ctx.get("item")
    if not isinstance(item, dict) or item.get("state") not in STATES:
        raise ItemError("this card is not an inbox item")
    return item


def move(ctx: Dict[str, Any], to: str, by: str = "", note: str = "",
         at: Optional[str] = None, outcome: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The context after moving the item to `to`. Refuses a move its state does not allow."""
    item = item_of(ctx)
    if to not in STATES:
        raise ItemError(f"no state {to!r}; an item is one of {', '.join(STATES)}")
    if to not in MOVES[item["state"]]:
        raise ItemError(f"an item that is {item['state']} cannot be moved to {to}")
    step: Dict[str, Any] = {"state": to, "at": at or _now(), "by": by}
    if note:
        step["note"] = str(note)[:500]
    nxt = {**item, "state": to, "history": [*(item.get("history") or []), step]}
    if outcome is not None:
        nxt["outcome"] = outcome
    return {**ctx, "item": nxt}


def outcome_of(status: int, result: Any, failure: Optional[str], at: Optional[str] = None) -> Dict[str, Any]:
    """What an approval's run returned, as recorded on the item."""
    return {"at": at or _now(), "status": status, "ok": failure is None,
            **({"error": failure} if failure else {}),
            "result": json.dumps(result)[:OUTCOME_CHARS]}
