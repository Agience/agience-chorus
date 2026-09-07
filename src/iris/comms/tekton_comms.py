"""The comms tekton — the condensor that terminates the message signal.

A tekton condenses a beam into an event and handles it; a facet only conducts. This tekton is the
terminator on both directions of the plane:

  * outbound — the guardian (the Claude agent of this ember) hands it a message; it condenses that
    into a signed record and puts it on the facet (the NAS plane).
  * inbound  — it reads what peers put on the plane (via the facet), condenses each into a delivered
    event (appended to the local guardian inbox so the guardian sees it even when it was away), and
    hands it up.

`build_comms_crystal` is the crystal: it assembles this tekton with the NAS facet for one node.
The guardian talks to the returned tekton (directly, or through the CLI in `__main__`). The ember
runs `watch()` as its standing comms plane — that is how "45 and 71 embers establish a watch/comms
plane via NAS", and the guardians drop/read through it.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Callable, List, Optional

from .message import Message
from .facet_nas import NasFacet


class CommsTekton:
    def __init__(self, node: str, peers: List[str], facet: NasFacet, inbox_dir):
        self.node = str(node)
        self.peers = [str(p) for p in peers if str(p) != str(node)]
        self.facet = facet
        self.inbox_dir = Path(inbox_dir)
        self.inbox_log = self.inbox_dir / f"inbox-{self.node}.jsonl"

    def establish(self) -> None:
        """Stand up the plane and the local inbox — idempotent."""
        self.facet.ensure_plane(self.peers)
        self.inbox_dir.mkdir(parents=True, exist_ok=True)

    # ── outbound ─────────────────────────────────────────────────────────────────────────────
    def send(self, to: str, body: str, *, kind: str = "note", subject: str = "",
             in_reply_to: Optional[str] = None) -> Message:
        msg = Message(frm=self.node, to=str(to), body=body, kind=kind,
                      subject=subject, ref=in_reply_to)
        self.facet.put(msg, peers=self.peers)          # peers used to fan out a broadcast ("*")
        return msg

    # ── inbound: condense + deliver ──────────────────────────────────────────────────────────
    def receive(self) -> List[Message]:
        """Consume new messages addressed to this node (its `to-<self>/` inbox), deliver each to the
        local inbox log, and return them. Exactly-once via the plane's `seen-<self>/` markers."""
        msgs = self.facet.poll(advance=True)
        if msgs:
            self.inbox_dir.mkdir(parents=True, exist_ok=True)
            with self.inbox_log.open("a", encoding="utf-8") as f:
                for m in msgs:
                    rec = {"received": time.time(), "frm": m.frm, "kind": m.kind,
                           "subject": m.subject, "body": m.body, "id": m.id,
                           "ref": m.ref, "ts": m.ts}
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return msgs

    def peek(self) -> List[Message]:
        """Inbound messages without consuming (does not mark them seen)."""
        return self.facet.poll(advance=False)

    def history(self) -> List[Message]:
        """Every message on the plane, all nodes, oldest-first — the full transcript."""
        return self.facet.transcript([self.node, *self.peers])

    # ── the standing plane ───────────────────────────────────────────────────────────────────
    def watch(self, *, interval: float = 20.0, on_message: Optional[Callable[[Message], None]] = None,
              max_ticks: Optional[int] = None) -> None:
        """The ember's standing comms loop: poll → deliver → (optional) react, forever.

        Delivery to the inbox log is unconditional (the guardian catches up later); `on_message` is
        an optional reactor (auto-ack, notify, hand to the guardian process)."""
        self.establish()
        ticks = 0
        while True:
            for m in self.receive():
                if on_message is not None:
                    try:
                        on_message(m)
                    except Exception:
                        pass
            ticks += 1
            if max_ticks is not None and ticks >= max_ticks:
                return
            time.sleep(max(1.0, float(interval)))


def build_comms_crystal(node: Optional[str] = None, *, root: Optional[str] = None,
                        peers: Optional[List[str]] = None, inbox_dir: Optional[str] = None
                        ) -> CommsTekton:
    """Assemble the comms crystal for one node: NAS facet (conduit) + comms tekton (condensor).

    Config resolves from args → env → default:
      node   COMMS_NODE / EMBER_NODE_ID            (default "71")
      root   COMMS_ROOT                            (REQUIRED — no default; see below)
      peers  COMMS_PEERS  (comma list, minus self) (default "45,71")
      inbox  COMMS_INBOX_DIR                       (default <store>/comms or ./comms-local)
    """
    node = str(node or os.getenv("COMMS_NODE") or os.getenv("EMBER_NODE_ID") or "71")
    # The comms plane is a share on the local network, so it is not derivable and no default here
    # could be right on another box. Refused rather than guessed: a node quietly establishing its
    # plane on a path no peer reads looks exactly like a node with no mail.
    root = root or os.getenv("COMMS_ROOT") or ""
    if not root:
        raise RuntimeError(
            "COMMS_ROOT is unset and no root was passed. Point it at the shared _comms plane "
            "this node joins, e.g. //<nas-host>/shared/agience/_comms.")
    peer_src = peers or (os.getenv("COMMS_PEERS") or "45,71,59,60").split(",")
    peers = [p.strip() for p in peer_src if p.strip() and p.strip() != node]
    if inbox_dir is None:
        # The inbox is small guardian-local metadata (a delivered-message log) — keep it off the
        # store drive so it never competes with the corpus for space. COMMS_INBOX_DIR is used
        # verbatim; otherwise a stable per-user dir.
        inbox_dir = os.getenv("COMMS_INBOX_DIR") or str(Path.home() / ".agience" / "comms")
    facet = NasFacet(root, node)
    tekton = CommsTekton(node, peers, facet, inbox_dir)
    tekton.establish()
    return tekton
