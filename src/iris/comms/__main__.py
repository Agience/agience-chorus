"""Guardian CLI for the ember comms plane.

The Claude agent (the guardian) of each ember drops and reads messages here; the ember runs
`watch` as its standing plane. Node/root/peers resolve from env (COMMS_NODE/EMBER_NODE_ID,
COMMS_ROOT, COMMS_PEERS) or flags.

  python -m crystal.comms init
  python -m crystal.comms send --to 45 --subject retrieval --body "freq prior fixes 9/10"
  python -m crystal.comms send --to 45 --body-file note.md --kind note
  python -m crystal.comms inbox           # consume + show new messages for me
  python -m crystal.comms peek            # show new without consuming
  python -m crystal.comms history         # full transcript, both directions
  python -m crystal.comms watch --interval 20   # the ember's standing loop
"""
from __future__ import annotations

import argparse
import sys
import time

from .tekton_comms import build_comms_crystal


def _fmt(m) -> str:
    subj = f" [{m.subject}]" if m.subject else ""
    reply = f" (re {m.ref})" if m.ref else ""
    return f"  {m.frm}->{m.to} {m.kind}{subj}{reply}  {m.ts}  id={m.id}\n    {m.body}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="crystal.comms", description="ember comms plane (guardian CLI)")
    ap.add_argument("--node"); ap.add_argument("--root"); ap.add_argument("--peers")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    s = sub.add_parser("send")
    s.add_argument("--to", required=True); s.add_argument("--subject", default="")
    s.add_argument("--kind", default="note"); s.add_argument("--reply-to", default=None)
    s.add_argument("--body", default=None); s.add_argument("--body-file", default=None)
    sub.add_parser("inbox"); sub.add_parser("peek"); sub.add_parser("history")
    w = sub.add_parser("watch")
    w.add_argument("--interval", type=float, default=20.0)
    w.add_argument("--max-ticks", type=int, default=None)
    a = ap.parse_args(argv)

    peers = a.peers.split(",") if a.peers else None
    tk = build_comms_crystal(a.node, root=a.root, peers=peers)

    if a.cmd == "init":
        print(f"comms plane ready: node={tk.node} peers={tk.peers} root={tk.facet.root}")
        return 0
    if a.cmd == "send":
        body = a.body
        if a.body_file:
            body = open(a.body_file, encoding="utf-8").read()
        if body is None:
            body = sys.stdin.read()
        m = tk.send(a.to, body, kind=a.kind, subject=a.subject, in_reply_to=a.reply_to)
        print(f"sent id={m.id} {m.frm}->{m.to} ({m.kind})")
        return 0
    if a.cmd in ("inbox", "peek"):
        msgs = tk.receive() if a.cmd == "inbox" else tk.peek()
        if not msgs:
            print(f"({tk.node}) no new messages" + ("" if a.cmd == "inbox" else " (peek)"))
            return 0
        print(f"({tk.node}) {len(msgs)} message(s):")
        for m in msgs:
            print(_fmt(m))
        return 0
    if a.cmd == "history":
        for m in tk.history():
            print(_fmt(m))
        return 0
    if a.cmd == "watch":
        print(f"watching plane as {tk.node} (peers={tk.peers}, every {a.interval}s) …")
        tk.watch(interval=a.interval, max_ticks=a.max_ticks,
                 on_message=lambda m: print(f"[{time.strftime('%H:%M:%S')}] IN {_fmt(m)}"))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
