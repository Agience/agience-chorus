"""The NAS facet — the conduit the school's comms signal propagates through.

One plane, matching 45's `iris/comms` layout so every node interoperates:

    <root>/to-<node>/<ts>-<from>-<id>.json    a node's inbox (anyone writes here to reach it)
    <root>/seen-<node>/<id>                    that node's dedup markers (consumed = touched)

`root` is the shared `_comms/` dir on the NAS. A node writes to a recipient's `to-<peer>/` inbox
(broadcast `*` fans out to every known peer) and reads its own `to-<self>/`, skipping ids already
in `seen-<self>/`. Atomic writes (tmp+rename); nothing is deleted on read (durable transcript).
Stdlib-only — a pupil Pi runs it on stock Python 3.9.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from .message import Message


class NasFacet:
    def __init__(self, root, node: str):
        self.root = Path(root)
        self.node = str(node)
        self.inbox = self.root / f"to-{self.node}"
        self.seen = self.root / f"seen-{self.node}"

    def ensure_plane(self, peers: List[str]) -> None:
        self.inbox.mkdir(parents=True, exist_ok=True)
        self.seen.mkdir(parents=True, exist_ok=True)
        for p in peers:
            (self.root / f"to-{p}").mkdir(parents=True, exist_ok=True)

    def put(self, msg: Message, peers: Optional[List[str]] = None) -> Message:
        targets = [p for p in (peers or []) if p != self.node] if msg.to == "*" else [msg.to]
        for t in targets:
            d = self.root / f"to-{t}"
            d.mkdir(parents=True, exist_ok=True)
            fn = msg.wire_filename()
            dst, tmp = d / fn, d / (fn + ".tmp")
            tmp.write_text(msg.to_json(), encoding="utf-8")
            os.replace(tmp, dst)                       # atomic publish
        return msg

    def poll(self, *, advance: bool = True) -> List[Message]:
        """Inbound messages for this node not yet seen, oldest-first. `advance` marks them seen."""
        out: List[Message] = []
        if not self.inbox.is_dir():
            return out
        self.seen.mkdir(parents=True, exist_ok=True)
        for f in sorted(self.inbox.glob("*.json")):
            try:
                msg = Message.from_json(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if (self.seen / msg.id).exists():
                continue
            out.append(msg)
            if advance:
                try:
                    (self.seen / msg.id).write_text("", encoding="utf-8")
                except OSError:
                    pass
        out.sort(key=lambda m: m.ts)
        return out

    def transcript(self, nodes: List[str]) -> List[Message]:
        """Every message on the plane (all inboxes), oldest-first — the full record."""
        seen_ids, allm = set(), []
        for n in nodes:
            d = self.root / f"to-{n}"
            if not d.is_dir():
                continue
            for f in sorted(d.glob("*.json")):
                try:
                    m = Message.from_json(f.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if m.id in seen_ids:
                    continue
                seen_ids.add(m.id)
                allm.append(m)
        allm.sort(key=lambda m: m.ts)
        return allm
