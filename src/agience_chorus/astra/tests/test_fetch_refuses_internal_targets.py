"""`op.fetch.get` goes through the shared egress guard: a numeric host in any spelling, and a name
that resolves to a non-public address, are refused before any connection is opened.

The connection primitive is replaced with one that fails the test, so a refusal is observed as the
absence of a connection attempt — not inferred from an error message, which a refused TCP connect
would also produce.
"""
from __future__ import annotations

import socket

import pytest

from agience_chorus.astra import fetch


@pytest.fixture
def no_connect(monkeypatch):
    attempts = []

    def _connect(address, *a, **k):
        attempts.append(address)
        raise AssertionError("a connection was opened to %r" % (address,))

    monkeypatch.setattr(socket, "create_connection", _connect)
    return attempts


def _resolver(table):
    def _gai(host, port, *a, **k):
        if host not in table:
            raise socket.gaierror("unknown %s" % host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (table[host], port))]
    return _gai


@pytest.mark.parametrize("url", [
    "http://2130706433/x", "http://0x7f000001/x", "http://0x7f.1/x", "http://017700000001/x",
    "http://127.1/x", "http://[::ffff:127.0.0.1]/x", "http://169.254.169.254/latest/meta-data/",
])
def test_numeric_host_forms_are_refused_without_connecting(url, no_connect):
    out = fetch._get({"url": url})
    assert out["ok"] is False
    assert no_connect == []


@pytest.mark.parametrize("name,address", [
    ("metadata.example", "169.254.169.254"), ("intranet.example", "10.0.0.5"),
    ("cgnat.example", "100.64.1.1"), ("mapped.example", "::ffff:127.0.0.1"),
])
def test_a_name_resolving_to_a_non_public_address_is_refused(name, address, no_connect,
                                                             monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _resolver({name: address}))
    out = fetch._get({"url": "http://%s/" % name})
    assert out["ok"] is False
    assert no_connect == []
