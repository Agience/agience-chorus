"""`agience_chorus._egress` refuses every target that is not a public unicast address.

The guard is the one outbound path for a caller-named URL (sage `web_retrieve`, iris `fetch_url`,
astra `op.fetch.get`). Pinned here:

  * spelling: numeric hosts in every form the C resolver accepts, local names, non-http schemes and
    URL credentials are refused before any lookup;
  * addresses: every non-public range, including IPv6 forms that embed a private IPv4 address;
  * resolution: a name is refused when ANY address it resolves to is non-public, and the connection
    goes to the checked address;
  * redirects: each hop is checked again, and the hop count is capped;
  * size and time: the body stops at the byte cap, and one deadline covers the whole exchange;
  * token endpoints: only the allowlisted OAuth endpoints pass.

Network: a local HTTP server on 127.0.0.1. The guard would refuse that address, so the test maps one
name (`public.test`) to it by replacing `_resolve` for that name only; every other name goes through
the real resolution check.
"""
from __future__ import annotations

import http.server
import socket
import threading
import time

import pytest

from agience_chorus import _egress


# ── spelling ──────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("host", [
    "127.0.0.1", "2130706433", "0x7f000001", "0x7f.1", "017700000001", "127.1", "0177.0.0.1",
    "10.0.0.1", "169.254.169.254", "8.8.8.8", "::1", "::ffff:127.0.0.1",
    "localhost", "LOCALHOST.", "db.localhost", "metadata.google.internal", "printer.local",
])
def test_numeric_and_local_hosts_are_refused_by_spelling(host):
    assert _egress.host_refused(host)


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "ftp://example.com/x", "gopher://example.com/", "http://[::1]/",
    "http://user:pw@example.com/", "http://127.0.0.1:8081/artifacts", "http:///nohost",
])
def test_check_url_refuses_without_resolving(url, monkeypatch):
    def _no_lookup(*a, **k):
        raise AssertionError("resolved a URL that should be refused by its spelling")
    monkeypatch.setattr(_egress.socket, "getaddrinfo", _no_lookup)
    with pytest.raises(_egress.EgressRefused):
        _egress.check_url(url)


def test_a_public_name_is_not_refused_by_spelling():
    assert _egress.host_refused("example.com") is None
    assert _egress.host_refused("arxiv.org") is None


# ── addresses ─────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("addr", [
    "127.0.0.1", "10.1.2.3", "172.16.0.1", "192.168.1.1", "169.254.169.254", "100.64.0.1",
    "0.0.0.0", "224.0.0.1", "239.255.255.250", "240.0.0.1", "255.255.255.255", "192.0.2.1",
    "::", "::1", "fe80::1", "fc00::1", "ff02::1",
    "::ffff:127.0.0.1", "::ffff:169.254.169.254", "::ffff:10.0.0.1",
    "64:ff9b::a9fe:a9fe", "2002:c0a8:0101::1", "2001:0:4136:e378:8000:63bf:3fff:fdd2",
])
def test_non_public_addresses_are_refused(addr):
    assert _egress.address_refused(addr)


@pytest.mark.parametrize("addr", ["8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"])
def test_public_addresses_pass(addr):
    assert _egress.address_refused(addr) is None


# ── resolution ────────────────────────────────────────────────────────────────────────────────────

_REAL_GETADDRINFO = socket.getaddrinfo


def _fake_getaddrinfo(table, fallback=None):
    """A resolver answering from `table`. `fallback` answers other names; the live-server tests
    need it because the socket connect resolves the numeric loopback address it is handed."""
    def _gai(host, port, *a, **k):
        if host not in table:
            if fallback is not None:
                return fallback(host, port, *a, **k)
            raise socket.gaierror("unknown %s" % host)
        return [(socket.AF_INET6 if ":" in a_ else socket.AF_INET, socket.SOCK_STREAM, 6, "",
                 (a_, port)) for a_ in table[host]]
    return _gai


def test_a_name_resolving_to_a_private_address_is_refused(monkeypatch):
    monkeypatch.setattr(_egress.socket, "getaddrinfo",
                        _fake_getaddrinfo({"intranet.example": ["10.0.0.5"]}))
    with pytest.raises(_egress.EgressRefused):
        _egress.check_url("http://intranet.example/")


def test_one_private_record_among_public_ones_refuses_the_name(monkeypatch):
    monkeypatch.setattr(_egress.socket, "getaddrinfo",
                        _fake_getaddrinfo({"mixed.example": ["93.184.216.34", "127.0.0.1"]}))
    with pytest.raises(_egress.EgressRefused):
        _egress.check_url("https://mixed.example/")


def test_a_public_name_is_pinned_to_its_checked_address(monkeypatch):
    monkeypatch.setattr(_egress.socket, "getaddrinfo",
                        _fake_getaddrinfo({"paper.example": ["93.184.216.34"]}))
    t = _egress.check_url("https://paper.example/a?b=1")
    assert (t.scheme, t.host, t.port, t.path, t.address) == (
        "https", "paper.example", 443, "/a?b=1", "93.184.216.34")


# ── a live exchange: redirects, byte cap, deadline ───────────────────────────────────────────────

class _Handler(http.server.BaseHTTPRequestHandler):
    routes: dict = {}

    def log_message(self, *a):
        pass

    def do_GET(self):
        route = self.routes.get(self.path)
        if route is None:
            self.send_response(404)
            self.end_headers()
            return
        route(self)


@pytest.fixture
def server(monkeypatch):
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    real_resolve = _egress._resolve

    def _resolve(host, p):
        return "127.0.0.1" if host == "public.test" else real_resolve(host, p)

    monkeypatch.setattr(_egress, "_resolve", _resolve)
    monkeypatch.setattr(_egress.socket, "getaddrinfo",
                        _fake_getaddrinfo({"metadata.test": ["169.254.169.254"]},
                                          fallback=_REAL_GETADDRINFO))
    _Handler.routes = {}
    try:
        yield "http://public.test:%d" % port, _Handler.routes
    finally:
        httpd.shutdown()
        httpd.server_close()


def _redirect(to):
    def _r(h):
        h.send_response(302)
        h.send_header("Location", to)
        h.end_headers()
    return _r


def _body(data: bytes, ctype="text/plain; charset=utf-8"):
    def _b(h):
        h.send_response(200)
        h.send_header("Content-Type", ctype)
        h.send_header("Content-Length", str(len(data)))
        h.end_headers()
        h.wfile.write(data)
    return _b


def test_a_permitted_fetch_returns_the_body_and_sends_the_name_as_host(server):
    base, routes = server
    seen = {}

    def _echo(h):
        seen["host"] = h.headers.get("Host")
        _body(b"hello")(h)
    routes["/ok"] = _echo
    r = _egress.fetch(base + "/ok")
    assert (r.status, r.body, r.truncated, r.text()) == (200, b"hello", False, "hello")
    assert seen["host"].startswith("public.test")


@pytest.mark.parametrize("target", [
    "http://169.254.169.254/latest/meta-data/", "http://127.0.0.1:8081/", "http://localhost/",
    "http://metadata.test/", "file:///etc/passwd", "http://[::ffff:127.0.0.1]/",
])
def test_every_redirect_hop_is_checked(server, target):
    base, routes = server
    routes["/go"] = _redirect(target)
    with pytest.raises(_egress.EgressRefused):
        _egress.fetch(base + "/go")


def test_a_relative_redirect_is_followed_and_checked(server):
    base, routes = server
    routes["/a"] = _redirect("/b")
    routes["/b"] = _body(b"landed")
    r = _egress.fetch(base + "/a")
    assert r.body == b"landed" and r.url.endswith("/b")


def test_the_redirect_count_is_capped(server):
    base, routes = server
    routes["/loop"] = _redirect("/loop")
    with pytest.raises(_egress.EgressRefused):
        _egress.fetch(base + "/loop", max_redirects=3)


def test_reading_stops_at_the_byte_cap(server):
    base, routes = server
    routes["/big"] = _body(b"x" * 200_000)
    r = _egress.fetch(base + "/big", max_bytes=1000)
    assert r.truncated is True and len(r.body) == 1000


def test_one_deadline_covers_a_slow_body(server):
    base, routes = server

    def _drip(h):
        h.send_response(200)
        h.send_header("Content-Length", "1000")
        h.end_headers()
        try:
            for _ in range(1000):
                h.wfile.write(b"x")
                h.wfile.flush()
                time.sleep(0.05)
        except OSError:
            pass
    routes["/drip"] = _drip
    t0 = time.monotonic()
    with pytest.raises(_egress.EgressError):
        _egress.fetch(base + "/drip", timeout=1.0)
    assert time.monotonic() - t0 < 5


# ── token endpoints ──────────────────────────────────────────────────────────────────────────────

def test_only_allowlisted_token_endpoints_pass():
    assert _egress.require_token_endpoint("https://oauth2.googleapis.com/token") == \
        "https://oauth2.googleapis.com/token"
    for bad in ("", None, "http://oauth2.googleapis.com/token", "https://evil.example/token",
                "https://oauth2.googleapis.com/token/../x", "http://169.254.169.254/"):
        with pytest.raises(_egress.EgressRefused):
            _egress.require_token_endpoint(bad)
