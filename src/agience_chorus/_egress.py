"""Outbound reach to a URL someone else chose — one guard for every persona that makes one.

A persona runs next to Mantle, Origin, the node's own admin ports and, on a cloud host, the metadata
service that hands out credentials. A tool that fetches a caller-supplied URL is therefore a way to
reach all of them unless the reach itself refuses. This module is that refusal, and the fetch that
goes through it:

  * only `http` and `https`;
  * the host is resolved here, and the fetch is refused unless EVERY address it resolves to is a
    public unicast address — no loopback, RFC 1918, link-local (169.254/16, fe80::/10), CGNAT
    (100.64/10), unspecified, multicast, reserved or documentation ranges, and no IPv6 form that
    embeds one of those (IPv4-mapped, 6to4, NAT64, Teredo);
  * a host written as a number — `127.0.0.1`, `2130706433`, `0x7f.1`, `[::1]` — is refused outright,
    as are `localhost` and the private suffixes, before any lookup;
  * the connection goes to the address that was checked, not to a second lookup of the name, so a
    name that resolves public once and private a moment later (DNS rebinding) cannot slip between
    the check and the connect. TLS still verifies the certificate against the name;
  * redirects are followed here, one hop at a time, and every hop is checked the same way; the
    number of hops is capped;
  * the method is GET and nothing else, the response is read in chunks and reading stops at the
    byte cap, and the whole exchange — every hop — shares one deadline.

stdlib only, so it can travel inside a bundle (`astra/fetch.py` carries it as a sibling module) as
well as be imported by the persona servers. Blocking: async callers run `fetch` in a thread.

Token-endpoint allowlist. An OAuth token exchange POSTs a client secret and a refresh token, so the
endpoint it goes to must be one this platform knows, never a value read from caller-editable
config. `require_token_endpoint` is that check, shared by iris and seraph.
"""
from __future__ import annotations

import http.client
import ipaddress
import re
import socket
import time
from dataclasses import dataclass
from typing import Dict, Optional
from urllib.parse import urljoin, urlsplit

ALLOWED_SCHEMES = frozenset({"http", "https"})
MAX_REDIRECTS = 5
MAX_TIMEOUT = 30.0
MAX_BYTES = 5_000_000
_CHUNK = 65536
_REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})

#: Known OAuth2 token endpoints. A token exchange to any other URL is refused. Adding a provider
#: means adding its endpoint here, in code, where the change is reviewed.
OAUTH_TOKEN_ENDPOINTS = frozenset({
    "https://oauth2.googleapis.com/token",
})

#: Refused whatever `ipaddress` says about them. `is_global` alone is not enough: it calls
#: multicast and NAT64 global, and its reading of CGNAT has changed across Python versions.
_REFUSED_NETS = tuple(ipaddress.ip_network(n) for n in (
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12",
    "192.0.0.0/24", "192.0.2.0/24", "192.168.0.0/16", "198.18.0.0/15", "198.51.100.0/24",
    "203.0.113.0/24", "224.0.0.0/4", "240.0.0.0/4",
    "::/128", "::1/128", "64:ff9b::/96", "64:ff9b:1::/48", "100::/64", "2001::/32", "2001:db8::/32",
    "2002::/16", "fc00::/7", "fe80::/10", "fec0::/10", "ff00::/8",
))

#: Names that mean "this machine" or "this private network" without being numbers.
_LOCAL_NAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"})
_LOCAL_SUFFIXES = (".localhost", ".local", ".internal", ".localdomain", ".home.arpa", ".lan")

#: A dotted label that the C resolver would read as part of a number: decimal, octal or hex.
_NUMERIC_LABEL = re.compile(r"^(0x[0-9a-f]*|[0-9]+)$")


class EgressError(Exception):
    """The fetch did not produce a response. The message is safe to hand back to a caller."""


class EgressRefused(EgressError):
    """The guard refused the URL, a redirect target, or a token endpoint."""


@dataclass(frozen=True)
class Response:
    url: str                 # the URL that answered, after redirects
    status: int
    content_type: str
    body: bytes
    truncated: bool          # the body stopped at the byte cap
    headers: Optional[Dict[str, str]] = None   # lower-cased names; set by `post`

    def text(self) -> str:
        """The body decoded by the charset the response declares, UTF-8 when it declares none."""
        m = re.search(r"charset=([\w.:-]+)", self.content_type or "", re.IGNORECASE)
        charset = (m.group(1) if m else "utf-8").strip("\"'")
        try:
            return self.body.decode(charset, "replace")
        except LookupError:
            return self.body.decode("utf-8", "replace")


def address_refused(ip) -> Optional[str]:
    """Why a connection to this address is refused, or None when it is a public unicast address."""
    ip = ipaddress.ip_address(ip)
    if ip.version == 6:
        embedded = ip.ipv4_mapped or ip.sixtofour or (ip.teredo[1] if ip.teredo else None)
        if embedded is not None:
            why = address_refused(embedded)
            if why:
                return "%s (embedded in %s)" % (why, ip)
    for net in _REFUSED_NETS:
        if ip.version == net.version and ip in net:
            return "%s is in the non-public range %s" % (ip, net)
    if ip.is_multicast or ip.is_unspecified or ip.is_reserved or not ip.is_global:
        return "%s is not a public unicast address" % ip
    return None


def host_refused(host: str) -> Optional[str]:
    """Why a URL host is refused by its spelling alone, before any lookup, or None."""
    h = (host or "").strip().lower().rstrip(".")
    if not h:
        return "the URL has no host"
    if ":" in h:
        return "a numeric (IPv6) host is refused: %s" % host
    try:
        ipaddress.ip_address(h)
        return "a numeric host is refused: %s" % host
    except ValueError:
        pass
    if all(_NUMERIC_LABEL.match(label) for label in h.split(".")):
        return "a numeric host is refused: %s" % host
    if h in _LOCAL_NAMES or h.endswith(_LOCAL_SUFFIXES):
        return "a local host name is refused: %s" % host
    try:
        h.encode("idna")
    except UnicodeError:
        return "the host is not a valid name: %s" % host
    return None


@dataclass(frozen=True)
class _Target:
    scheme: str
    host: str
    port: int
    path: str
    address: str             # the checked address the connection goes to


def _resolve(host: str, port: int) -> str:
    """The address to connect to. Every address the name resolves to must pass, not just one:
    a name with one public and one private record would otherwise be reachable on the private one
    whenever the resolver's order changes."""
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError) as exc:
        raise EgressError("cannot resolve %s: %s" % (host, exc)) from None
    addresses = []
    for _family, _type, _proto, _canon, sockaddr in infos:
        addr = sockaddr[0].split("%", 1)[0]
        why = address_refused(addr)
        if why:
            raise EgressRefused("refusing %s: %s" % (host, why))
        addresses.append(addr)
    if not addresses:
        raise EgressError("cannot resolve %s" % host)
    return addresses[0]


def check_url(url: str) -> _Target:
    """Validate one URL and resolve its host. Raises `EgressRefused` naming the reason."""
    try:
        parts = urlsplit((url or "").strip())
        port = parts.port
    except ValueError as exc:
        raise EgressRefused("malformed URL: %s" % exc) from None
    scheme = (parts.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        raise EgressRefused("scheme %r is refused (http/https only)" % scheme)
    if parts.username is not None or parts.password is not None:
        raise EgressRefused("credentials in the URL are refused")
    host = parts.hostname or ""
    why = host_refused(host)
    if why:
        raise EgressRefused(why)
    port = port or (443 if scheme == "https" else 80)
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    return _Target(scheme, host, port, path, _resolve(host, port))


class _PinnedHTTP(http.client.HTTPConnection):
    """Connects to the checked address; the Host header still carries the name."""

    def __init__(self, target: _Target, timeout: float):
        super().__init__(target.host, target.port, timeout=timeout)
        self._address = target.address

    def connect(self):
        self.sock = socket.create_connection((self._address, self.port), self.timeout)


class _PinnedHTTPS(http.client.HTTPSConnection):
    """Connects to the checked address; SNI and certificate verification use the name."""

    def __init__(self, target: _Target, timeout: float):
        super().__init__(target.host, target.port, timeout=timeout)
        self._address = target.address

    def connect(self):
        sock = socket.create_connection((self._address, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def fetch(url: str, *, timeout: float = 20.0, max_bytes: int = MAX_BYTES,
          max_redirects: int = MAX_REDIRECTS, headers: Optional[Dict[str, str]] = None) -> Response:
    """GET `url` through the guard. Raises `EgressRefused` for a refused URL or hop and
    `EgressError` for any other failure to get a response; an HTTP error status is a response."""
    timeout = max(0.1, min(float(timeout or MAX_TIMEOUT), MAX_TIMEOUT))
    max_bytes = max(0, min(int(max_bytes), MAX_BYTES))
    max_redirects = max(0, min(int(max_redirects), MAX_REDIRECTS))
    deadline = time.monotonic() + timeout
    sent = {"User-Agent": "Agience/1.0", "Accept-Encoding": "identity", "Connection": "close"}
    for k, v in (headers or {}).items():
        if k.lower() not in ("host", "accept-encoding", "connection"):
            sent[k] = v

    current = url
    for _hop in range(max_redirects + 1):
        target = check_url(current)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise EgressError("timed out after %ss" % timeout)
        conn_cls = _PinnedHTTPS if target.scheme == "https" else _PinnedHTTP
        conn = conn_cls(target, remaining)
        try:
            conn.request("GET", target.path, headers=sent)
            resp = conn.getresponse()
            location = resp.getheader("Location")
            if resp.status in _REDIRECT_CODES and location:
                current = urljoin(current, location.strip())
                continue
            body, truncated = _read(conn, resp, deadline, timeout, max_bytes)
            return Response(current, resp.status, resp.getheader("Content-Type") or "",
                            body, truncated)
        except EgressError:
            raise
        except (OSError, http.client.HTTPException, ValueError) as exc:
            raise EgressError("fetch failed: %s" % type(exc).__name__) from None
        finally:
            conn.close()
    raise EgressRefused("more than %d redirects" % max_redirects)


def _read(conn, resp, deadline: float, timeout: float, max_bytes: int):
    """The body, read in chunks against the shared deadline and stopped at the byte cap."""
    chunks, size, truncated = [], 0, False
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise EgressError("timed out after %ss" % timeout)
        if conn.sock is not None:
            conn.sock.settimeout(remaining)
        # read1: at most one read from the socket, so the deadline is checked between
        # every arrival rather than after a buffered read that waits for the full amount.
        chunk = resp.read1(min(_CHUNK, max_bytes - size + 1))
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
        if size > max_bytes:
            truncated = True
            break
    return b"".join(chunks)[:max_bytes], truncated


def post(url: str, body: bytes, *, timeout: float = 20.0, max_bytes: int = MAX_BYTES,
         headers: Optional[Dict[str, str]] = None) -> Response:
    """POST `body` to `url` through the same guard as `fetch`, for a protocol that needs it (an
    MCP server's JSON-RPC endpoint). A redirect is refused rather than followed: re-sending a
    request body to wherever a server points is how a guarded POST turns into an unguarded one.
    The response carries its headers (`Response.headers`, lower-cased)."""
    timeout = max(0.1, min(float(timeout or MAX_TIMEOUT), MAX_TIMEOUT))
    max_bytes = max(0, min(int(max_bytes), MAX_BYTES))
    deadline = time.monotonic() + timeout
    sent = {"User-Agent": "Agience/1.0", "Accept-Encoding": "identity", "Connection": "close"}
    for k, v in (headers or {}).items():
        if k.lower() not in ("host", "accept-encoding", "connection", "content-length"):
            sent[k] = v
    target = check_url(url)
    conn_cls = _PinnedHTTPS if target.scheme == "https" else _PinnedHTTP
    conn = conn_cls(target, max(0.1, deadline - time.monotonic()))
    try:
        conn.request("POST", target.path, body=body, headers=sent)
        resp = conn.getresponse()
        if resp.status in _REDIRECT_CODES:
            raise EgressRefused("the server redirected a POST; redirects are not followed")
        data, truncated = _read(conn, resp, deadline, timeout, max_bytes)
        return Response(url, resp.status, resp.getheader("Content-Type") or "", data, truncated,
                        {k.lower(): v for k, v in resp.getheaders()})
    except EgressError:
        raise
    except (OSError, http.client.HTTPException, ValueError) as exc:
        raise EgressError("request failed: %s" % type(exc).__name__) from None
    finally:
        conn.close()


def require_token_endpoint(url: Optional[str]) -> str:
    """The token endpoint, if it is one this platform knows. Raises `EgressRefused` otherwise."""
    endpoint = (url or "").strip()
    if endpoint not in OAUTH_TOKEN_ENDPOINTS:
        raise EgressRefused(
            "token endpoint %r is not an allowed OAuth token endpoint" % (endpoint[:200],))
    return endpoint
