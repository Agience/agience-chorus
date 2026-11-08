"""A secret is sent only to an endpoint its own credential names (review 10, R1).

Invoke lets a caller have a credential used for them; it must not let them choose where the secret
goes. Before this, a caller holding only Invoke on a team credential wrote their own MCP-server
card naming it and their own URL, and Iris sent the team's secret there.

The credential names the endpoints it may be sent to (`allowed_endpoints`), fixed by whoever wrote
it, who holds Admin on it by creation. The list is sealed to the persona with the secret, so Mantle
cannot alter it, and Mantle's `/use` returns the same list beside the sealed copy. The persona
refuses a copy that names no endpoint, a binding that differs from the sealed one, and any endpoint
the credential does not name, before it sends anything.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from agience_chorus import _secrets
from prism.trust import sealing

TEAM = "https://mcp.team.example/mcp"


def _jwk(key, kid):
    n = key.public_key().public_numbers()

    def b(i):
        return sealing._b64(i.to_bytes((i.bit_length() + 7) // 8, "big"))

    return {"kty": "RSA", "kid": kid, "n": b(n.n), "e": b(n.e)}


class _Resp:
    def __init__(self, body, status=200):
        self.status_code, self._body = status, body

    def json(self):
        return self._body

    def raise_for_status(self):
        pass


class _Client:
    def __init__(self, body):
        self.body, self.sent = body, []

    async def post(self, url, headers=None, json=None, timeout=None):
        self.sent.append((url, json))
        return _Resp(self.body(json) if callable(self.body) else self.body)


#: Origin's issuers for the test in progress (`origin_issuer`): a persona opens a copy only on
#: Origin's verdict for its own delegation (review 21), so each use here carries both.
_ORIGIN = {}


@pytest.fixture
def iris_key(monkeypatch, origin_issuer):
    _ORIGIN["issuer"] = origin_issuer
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(_secrets.service_identity, "load_persona_identity",
                        lambda persona: SimpleNamespace(private_key=key, kid="iris-1"))
    return key


def _sealed(key, payload, context="cred-1"):
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return sealing.seal(raw, sealing.public_key_from_jwk(_jwk(key, "iris-1")), kid="iris-1",
                        context=context)


def _use(body, endpoint):
    issuer = _ORIGIN["issuer"]
    dlg = issuer.delegation("iris", "person-1")
    served = body
    # Origin's verdict names the copy and list served as the writer's, and this use's nonce.

    def answer(request):
        return {**served, "verdict": issuer.verdict(
            "iris", dlg, "cred-1", "card-1", sealed=served.get("sealed"),
            endpoints=served.get("endpoints") or [], nonce=request.get("nonce"))}
    return asyncio.run(_secrets.use_secret(_Client(answer), "http://mantle.test", "cred-1",
                                           "card-1", {"Authorization": f"Bearer {dlg}"}, "iris",
                                           endpoint=endpoint))


def test_a_named_endpoint_gets_the_secret(iris_key):
    sealed = _sealed(iris_key, {"material": "TEAM-SECRET", "endpoints": [TEAM]})
    assert _use({"sealed": sealed, "endpoints": [TEAM]}, TEAM) == "TEAM-SECRET"
    assert _use({"sealed": sealed, "endpoints": [TEAM]}, TEAM + "/v2") == "TEAM-SECRET"


@pytest.mark.parametrize("endpoint", [
    "https://attacker.example/mcp",          # another host
    "http://mcp.team.example/mcp",           # another scheme
    "https://mcp.team.example:8443/mcp",     # another port
    "https://mcp.team.example/other",        # outside the named path
    "https://mcp.team.example/mcpx",         # a prefix that is not a path boundary
    "https://mcp.team.example.attacker.example/mcp",
])
def test_an_endpoint_the_credential_does_not_name_gets_nothing(iris_key, endpoint):
    sealed = _sealed(iris_key, {"material": "TEAM-SECRET", "endpoints": [TEAM]})
    with pytest.raises(_secrets.SecretUnavailable, match="does not name"):
        _use({"sealed": sealed, "endpoints": [TEAM]}, endpoint)


def test_a_credential_that_names_no_endpoint_is_used_nowhere(iris_key):
    sealed = _sealed(iris_key, b"TEAM-SECRET")        # written before endpoints were bound
    with pytest.raises(_secrets.SecretUnavailable, match="names no endpoint"):
        _use({"sealed": sealed}, TEAM)


def test_a_binding_mantle_altered_is_refused(iris_key):
    sealed = _sealed(iris_key, {"material": "TEAM-SECRET", "endpoints": [TEAM]})
    with pytest.raises(_secrets.SecretUnavailable, match="differ from"):
        _use({"sealed": sealed, "endpoints": [TEAM, "https://attacker.example/"]},
             "https://attacker.example/")


def test_an_invoke_only_caller_cannot_route_the_team_secret_to_their_own_endpoint(
        iris_key, monkeypatch):
    """The reviewer's probe, end to end through Iris: the caller's own card names the team
    credential and their own URL. Nothing is sent."""
    from agience_chorus.iris import server

    sealed = _sealed(iris_key, {"material": "TEAM-SECRET", "endpoints": [TEAM]},
                     context="team-credential")
    reached = []

    class _C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None, params=None, **k):
            if url.endswith("/grants/my-access"):
                return _Resp({"allowed": True})
            return _Resp({"id": "attacker-card",
                          "content_type": "application/vnd.agience.mcp-server+json",
                          "context": json.dumps({"url": "https://attacker.example/mcp",
                                                 "transport": {"type": "http",
                                                               "secret_id": "team-credential"}})})

        async def post(self, url, headers=None, json=None, timeout=None):
            return _Resp({"id": "team-credential", "sealed": sealed, "endpoints": [TEAM],
                          "verdict": issuer.verdict("iris", dlg, "team-credential",
                                                    "attacker-card", sealed=sealed,
                                                    endpoints=[TEAM],
                                                    nonce=(json or {}).get("nonce"))})

    issuer = _ORIGIN["issuer"]
    dlg = issuer.delegation("iris", "person-1")
    monkeypatch.setattr(server.httpx, "AsyncClient", _C)
    monkeypatch.setattr(server, "_require_user_headers",
                        lambda: {"Authorization": f"Bearer {dlg}"})
    monkeypatch.setattr(server, "_mcp_exchange",
                        lambda endpoint, method, params, auth: reached.append((endpoint, auth)) or {})
    out = json.loads(asyncio.run(server.call_mcp_server("attacker-card", "tools/list")))
    assert reached == [] and out.get("status") == 403 and "does not name" in out["error"]
