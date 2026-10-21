"""A workflow's runs: each one a Run card, and each step's output in reach of the steps after it.

Every run writes a `vnd.agience.run+json` card: the workflow it ran, when, its status, and for each
step its status, output and error. The card is the run's record, open to anyone who can read it,
the way a person inspects what a routine did; the runner also reads it (a step's `condition`, a
`retry`'s field).

A step's inputs can name what an earlier step returned:

    $.previous                 the output of the step just before
    $.previous.reconciliation_id
    $.steps.<name>             the output of the step called <name>
    $.steps.<name>.items[0].id

An output is the step's answer as the tool gave it: a JSON value when its text is JSON, the text
otherwise. Paths walk objects by key and lists by `[N]`; a path that leads nowhere leaves the
argument out, so the tool sees it missing rather than wrong.

A step is an operator (`{"name", "key", "operator_id", "arguments"}`), invoked through its grant.
An argument naming an artifact is a typed link from the workflow (`@link.<key>.<argument>`), so
what the workflow works on is in the graph, not typed into a string; the runner reads the link as
the person running it, and a link they cannot read is not there.

Pure: no I/O.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

RUN_TYPE = "application/vnd.agience.run+json"
#: The most of a step's output the Run card carries; the runner keeps the whole for later steps.
OUTPUT_CHARS = 4000
_PART = re.compile(r"([^.\[\]]+)|\[(\d+)\]")
_MISSING = object()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve(path: str, scope: Dict[str, Any]) -> Any:
    """The value at `path` (`a.b[0].c`, without the `$.`) in `scope`, or `_MISSING`."""
    cur: Any = scope
    for key, index in _PART.findall(path):
        if key:
            if not isinstance(cur, dict) or key not in cur:
                return _MISSING
            cur = cur[key]
        else:
            i = int(index)
            if not isinstance(cur, list) or i >= len(cur):
                return _MISSING
            cur = cur[i]
    return cur


def resolve_mapping(mapping: Dict[str, Any], scope: Dict[str, Any]) -> Dict[str, Any]:
    """`mapping` with each `$.path` value read from `scope`; literals as they are; a path that
    leads nowhere leaves its argument out."""
    out: Dict[str, Any] = {}
    for key, value in (mapping or {}).items():
        if isinstance(value, str) and value.startswith("$."):
            found = resolve(value[2:], scope)
            if found is not _MISSING and found is not None:
                out[key] = found
        else:
            out[key] = value
    return out


LINK = "@link."


class LinkMissing(ValueError):
    """A step names a link the workflow does not have, or one the runner may not read."""


def link_name(key: str, argument: str) -> str:
    return f"{key}.{argument}"


def resolve_links(mapping: Dict[str, Any], links: Dict[str, str]) -> Dict[str, Any]:
    """`mapping` with each `@link.<name>` value replaced by the id the workflow links by that name."""
    out: Dict[str, Any] = {}
    for key, value in (mapping or {}).items():
        if isinstance(value, str) and value.startswith(LINK):
            name = value[len(LINK):]
            if name not in links:
                raise LinkMissing(f"argument '{key}': the workflow has no link '{name}' you may read")
            out[key] = links[name]
        else:
            out[key] = value
    return out


def output_of(result: Any) -> Any:
    """A step's answer, out of the MCP result that carries it (once more when a Transform passes
    its tool's result on whole): a JSON value when the text is JSON, the text otherwise."""
    for _ in range(3):
        if not (isinstance(result, dict) and isinstance(result.get("content"), list)):
            break
        blocks = result["content"]
        text = blocks[0].get("text", "") if blocks and isinstance(blocks[0], dict) else ""
        try:
            result = json.loads(text)
        except (TypeError, ValueError):
            return text
    if isinstance(result, str):
        try:
            return json.loads(result)
        except ValueError:
            return result
    return result


def shown(value: Any) -> str:
    """An output as the Run card carries it."""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=1)
    return text if len(text) <= OUTPUT_CHARS else text[:OUTPUT_CHARS] + " …"


def new_run(workflow_id: str, workflow_title: str, steps: List[dict], at: Optional[str] = None) -> dict:
    at = at or now()
    return {
        "title": f"{workflow_title or 'Workflow'} — run {at[:16].replace('T', ' ')} UTC",
        "content_type": RUN_TYPE,
        "workflow_id": workflow_id,
        "status": "running",
        "started_at": at,
        "steps": [{"index": i, "name": s.get("name") or f"step_{i}",
                   **({"operator_id": s["operator_id"]} if s.get("operator_id")
                      else {"transform_id": s.get("transform_id")}),
                   "status": "pending"} for i, s in enumerate(steps)],
    }


def mark(run: dict, index: int, status: str, *, output: Any = _MISSING, error: str = "",
         at: Optional[str] = None) -> dict:
    """`run` with step `index` moved to `status`, carrying its output or error."""
    steps = [dict(s) for s in run.get("steps") or []]
    while len(steps) <= index:
        steps.append({"index": len(steps), "status": "pending"})
    s = steps[index]
    s["status"] = status
    stamp = at or now()
    if status == "running":
        s["started_at"] = stamp
    else:
        s["finished_at"] = stamp
    if output is not _MISSING:
        s["output"] = shown(output)
    if error:
        s["error"] = error[:1000]
    return {**run, "steps": steps}


def finish(run: dict, status: str, error: str = "", at: Optional[str] = None) -> dict:
    return {**run, "status": status, "finished_at": at or now(), **({"error": error[:1000]} if error else {})}
