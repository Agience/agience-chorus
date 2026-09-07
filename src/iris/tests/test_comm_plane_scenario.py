"""A concrete distributed network on the communication plane — it works everywhere (a LAN for co-located
devices and the internet for remote ones), and it addresses any artifact (a group collection or an
individual ember, direct). John's phone is a chat facet onto his assistant, not a node. Every unit shown.
Diagrams: `_scratch/comms-network.md`. L2 scenario of `TEST-ARCHITECTURE.md`.

The units:
  Embers (plane nodes) and the carriers they sit on:
    coordinator-45   John's site (node 45)      lan, net    local coordinator — bridges LAN and internet
    deskbot          John's site, local device  lan         LAN-only (no internet at all)
    assistant-71     node 71                    net         John's personal assistant
    alice            an associate's home        net         a collaborator (another continent)
    cloud            a cloud VPS                net         the public interface
  Facet (a view, not a node):
    phone            John's phone — a chat view onto assistant-71 (rides its keys/groups). "Just chat."

  Carriers:  lan (John's local network: coordinator-45 + deskbot) · net (the internet: everyone else)
  coordinator-45 is on both — its `reconcile()` carries leaves between the LAN and the internet.

The groups (collection artifacts) and the ember address (agent artifact):
  home     = {coordinator-45, deskbot}                 — John's local devices
  project  = {coordinator-45, assistant-71, alice}     — the collaboration
  public   = {cloud}                                   — the world interface
  <assistant-71>  the ember's own address              — a direct message target (a group of one)
"""
from __future__ import annotations



from prism.carriers import InMemoryCarrier, reconcile  # noqa: E402
from prism.plane import Keyring, Lightcone, Plane  # noqa: E402

# 2026-08-26: a dead `sys.path` insert stood here and is removed. MEASURED per file — the
# inserts were neutralised, this file's tests run, and it passed; the full chorus suite then
# confirmed no global side effect (861 passed). `pytest.ini:34` (`pythonpath = src`) is what
# puts `src` on the path. Eight sibling test files KEEP theirs and must — see
# `agience-build/tighten/STATE.json`, finding `thirty-five-dead-path-inserts`.


class ChatFacet:
    """The phone — a thin chat view on an ember (a facet: passes and displays; not a plane node). No keys,
    groups, or carrier of its own — it rides the ember it views. 'My phone — just chat.'"""

    def __init__(self, ember: Plane, node: str):
        self._e, self._node = ember, node

    def chat(self):
        return sorted(m["signal"]["m"] for m in self._e.receive(self._node))

    def say(self, to: str, text: str):
        return self._e.send(to, {"m": text}, frm=self._node)


def _build():
    kr = Keyring(b"acme-collab-root")
    lc = (Lightcone()
          .define_group("home").define_group("project").define_group("public")
          .join("coordinator-45", "home").join("deskbot", "home")
          .join("coordinator-45", "project").join("assistant-71", "project").join("alice", "project")
          .join("cloud", "public"))
    lan, net = InMemoryCarrier(), InMemoryCarrier()
    subs = {"lan": lan, "net": net}

    def _clk():
        _clk.n += 1
        return _clk.n
    _clk.n = 0

    def ember(node, carriers):
        return Plane(node=node, keyring=kr, lightcone=lc, carriers=[subs[c] for c in carriers], clock=_clk)

    embers = {
        "coordinator-45": ember("coordinator-45", ["lan", "net"]),   # the bridge
        "deskbot": ember("deskbot", ["lan"]),                        # LAN-only
        "assistant-71": ember("assistant-71", ["net"]),
        "alice": ember("alice", ["net"]),
        "cloud": ember("cloud", ["net"]),
    }
    return kr, lc, subs, embers


def _converge(embers, rounds=2):
    for _ in range(rounds):
        for e in embers.values():
            e.reconcile()          # coordinator-45 carries leaves between the LAN and the internet


def _rx(embers, node):
    return sorted(m["signal"]["m"] for m in embers[node].receive(node))


def test_works_everywhere_groups_and_direct_ember_targets():
    kr, lc, subs, embers = _build()
    phone = ChatFacet(embers["assistant-71"], "assistant-71")     # John's phone = chat view on his assistant

    embers["coordinator-45"].send("home", {"m": "lights on"})            # group, on the LAN
    embers["coordinator-45"].send("project", {"m": "kickoff Monday"})    # group, across the internet
    embers["coordinator-45"].send("assistant-71", {"m": "check the logs"})  # ember (direct message)
    embers["cloud"].send("public", {"m": "status: all green"})           # group
    _converge(embers)

    # Works on the LAN: deskbot has no internet, yet receives the home-group message over the LAN.
    assert _rx(embers, "deskbot") == ["lights on"]

    # Works on the internet: a remote collaborator receives the project message; the coordinator bridged
    # it from the LAN it was sent on, out to the internet.
    assert "kickoff Monday" in _rx(embers, "alice")

    # Group vs direct-ember target: `project` (a collection) reached three; the direct message to the
    # ember `assistant-71` reached exactly one — only 71.
    assert {n for n in embers if "kickoff Monday" in _rx(embers, n)} == {"coordinator-45", "assistant-71", "alice"}
    assert {n for n in embers if "check the logs" in _rx(embers, n)} == {"assistant-71"}

    # The phone is just chat: it views the assistant — John sees the project message and his direct
    # message. It is not a node and holds no keys of its own.
    assert phone.chat() == ["check the logs", "kickoff Monday"]
    phone.say("project", "on my way")                            # John replies from his phone, through 71
    _converge(embers)
    assert "on my way" in _rx(embers, "alice")

    # Isolation everywhere: deskbot (home only) gets neither project, the DM, nor public; alice (project
    # only) gets neither home nor the DM nor public; the public is its own world.
    assert _rx(embers, "deskbot") == ["lights on"]               # not project / DM / public
    assert set(_rx(embers, "alice")) == {"kickoff Monday", "on my way"}   # not home / DM / public
    assert _rx(embers, "cloud") == ["status: all green"]


def test_full_delivery_matrix_matches_the_oracle():
    kr, lc, subs, embers = _build()
    msgs = {"home": ("coordinator-45", "lights on"),
            "project": ("coordinator-45", "kickoff Monday"),
            "assistant-71": ("coordinator-45", "check the logs"),   # a direct ember target
            "public": ("cloud", "status: all green")}
    for target, (sender, m) in msgs.items():
        embers[sender].send(target, {"m": m})
    _converge(embers)
    for node in embers:
        got = set(_rx(embers, node))
        expected = {m for target, (_s, m) in msgs.items() if target in lc.reaches(node)}   # the oracle
        assert got == expected, "%s: got %s, oracle %s" % (node, sorted(got), sorted(expected))


def test_offline_associate_catches_up_on_reconnect():
    """A globe node (the associate) drops off, then reconnects — store-and-forward: the coordination
    waited on the rendezvous and lands on reconnect, exactly once. Anti-entropy, nothing special."""
    kr, lc, subs, embers = _build()
    net = subs["net"]
    alice_box = InMemoryCarrier()
    alice = Plane(node="alice", keyring=kr, lightcone=lc, carriers=[alice_box])
    embers["coordinator-45"].send("project", {"m": "kickoff Monday"})
    embers["coordinator-45"].reconcile()                         # push LAN → internet
    assert alice.receive("alice") == []                          # alice offline
    reconcile(net, alice_box)
    reconcile(net, alice_box)                                    # idempotent
    assert [m["signal"]["m"] for m in alice.receive("alice")] == ["kickoff Monday"]
