"""The message — the signal on the school's comms plane.

One plane for all four nodes. This speaks the same wire form as 45's `iris/comms`
(`_comms/to-<peer>/` + `seen-<self>/`), so 45's native ember loop and the lightweight guardian CLI
here interoperate on one plane. Wire keys: `id, from, to, ts, kind, subject, body, ref`. `ts` is a
UTC ISO-8601 string. Stdlib-only, so a pupil Pi runs it on its stock Python 3.9 before its full
ember (Python 3.11) is even built.
"""
from __future__ import annotations

import json
import re
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Dict


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _short_id(frm: str, to: str, ts: str, subject: str, body: str) -> str:
    """Content-addressed short id = de-dup key (same message re-dropped = same id)."""
    h = hashlib.sha256("\n".join((frm, to, ts, subject, body)).encode("utf-8")).hexdigest()
    return h[:12]


@dataclass
class Message:
    frm: str                                  # sending node id ("71","45","59","60")
    to: str                                   # recipient node id, or "*" broadcast
    body: str
    kind: str = "note"                        # note | ack | query | answer | lesson | alert
    subject: str = ""
    ref: Optional[str] = None                 # in-reply-to id
    ts: str = field(default_factory=_now_iso)
    id: str = ""                              # filled from content if empty

    def __post_init__(self):
        if not self.id:
            self.id = _short_id(self.frm, self.to, self.ts, self.subject, self.body)

    def to_wire(self) -> Dict:
        return {"id": self.id, "from": self.frm, "to": self.to, "ts": self.ts,
                "kind": self.kind, "subject": self.subject, "body": self.body, "ref": self.ref}

    def to_json(self) -> str:
        return json.dumps(self.to_wire(), ensure_ascii=False, indent=2)

    @staticmethod
    def from_wire(w: Dict) -> "Message":
        return Message(frm=str(w.get("from")), to=str(w.get("to")), body=str(w.get("body") or ""),
                       kind=str(w.get("kind") or "note"), subject=str(w.get("subject") or ""),
                       ref=w.get("ref"), ts=str(w.get("ts") or _now_iso()), id=str(w.get("id") or ""))

    @staticmethod
    def from_json(text: str) -> "Message":
        return Message.from_wire(json.loads(text))

    def wire_filename(self) -> str:
        ts = re.sub(r"[^0-9TZ]", "", self.ts) or "00000000T000000Z"
        return "%s-%s-%s.json" % (ts, self.frm, self.id)

    def for_node(self, node: str) -> bool:
        return self.to == node or self.to == "*"

    def one_line(self) -> str:
        subj = f" [{self.subject}]" if self.subject else ""
        return f"{self.frm}->{self.to} {self.kind}{subj}: {self.body[:80]}"
