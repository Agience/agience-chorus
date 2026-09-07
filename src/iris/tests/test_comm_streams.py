"""Live stream channels (`prism.streams`; there is no `iris/comms/streams.py` re-export shim) — the
second transport mode. The invariants match the
message plane: frames are sealed (isolation is cryptographic), HLC-ordered (arrival-independent), and a
frame with no live receiver degrades to a store-and-forward leaf. Loopback fabric — no WebRTC/RF needed;
the semantics are what a real fabric must preserve. See `agience-pharos/genesis/DATA-COMMS-CHANNELS.md`."""
from __future__ import annotations



from prism.carriers import InMemoryCarrier  # noqa: E402
from prism.plane import HLC, Keyring, Lightcone, receive  # noqa: E402
from prism.streams import LoopbackFabric, StreamReceiver, open_stream  # noqa: E402

# 2026-08-26: a dead `sys.path` insert stood here and is removed. MEASURED per file — the
# inserts were neutralised, this file's tests run, and it passed; the full chorus suite then
# confirmed no global side effect (861 passed). `pytest.ini:34` (`pythonpath = src`) is what
# puts `src` on the path. Eight sibling test files KEEP theirs and must — see
# `agience-build/tighten/STATE.json`, finding `thirty-five-dead-path-inserts`.


def _clk():
    _clk.n += 1
    return _clk.n
_clk.n = 0


def test_live_frames_flow_sealed_ordered_and_isolated():
    kr = Keyring(b"root")
    lc = Lightcone().define_group("call").join("alice", "call").join("bob", "call").join("mallory", "other")
    fabric = LoopbackFabric()

    member = StreamReceiver("bob", lc, kr)          # in `call` → entitled
    outsider = StreamReceiver("mallory", lc, kr)    # not in `call`
    fabric.subscribe("call", member.on_leaf)
    fabric.subscribe("call", outsider.on_leaf)      # subscribed to the transport, but lacks the key

    s = open_stream(fabric, "call", keyring=kr, node="alice", hlc=HLC("alice", clock=_clk))
    s.send_frame({"t": 0, "v": [1, 0]})
    s.send_frame({"t": 1, "v": [0, 1]})

    assert [f["frame"]["t"] for f in member.frames] == [0, 1]     # live + HLC-ordered
    assert outsider.frames == []                                 # isolation: no key → opens nothing


def test_frame_degrades_to_a_store_and_forward_leaf_when_no_one_is_live():
    kr = Keyring(b"root")
    lc = Lightcone().define_group("call").join("alice", "call").join("bob", "call")
    fallback = InMemoryCarrier()
    fabric = LoopbackFabric(fallback=fallback)                    # no live subscribers on `call`

    s = open_stream(fabric, "call", keyring=kr, node="alice", hlc=HLC("alice", clock=_clk))
    s.send_frame({"t": 0, "v": [1, 0]})                          # nobody live → degrades

    assert len(fallback) == 1                                    # it landed on the durable carrier
    got = receive(fallback, principal="bob", lightcone=lc, keyring=kr)   # bob receives it store-and-forward
    assert [m["signal"]["t"] for m in got] == [0]


def test_closed_stream_refuses_further_frames():
    kr = Keyring(b"root")
    lc = Lightcone().define_group("call").join("alice", "call")
    s = open_stream(LoopbackFabric(), "call", keyring=kr, node="alice", hlc=HLC("alice", clock=_clk))
    s.close()
    try:
        s.send_frame({"t": 0})
        assert False, "a closed stream must refuse"
    except RuntimeError:
        pass
