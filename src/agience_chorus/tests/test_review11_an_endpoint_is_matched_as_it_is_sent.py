"""Review 11: a credential's endpoint is matched as the sender will reach it.

The path is normalised (`..`, `.`, and percent-encoded separators) before it is compared, and an
endpoint that carries a user part (`user@host`), a backslash, whitespace or control characters, or
a host that is not plain ASCII is refused, since the senders would read those differently.
"""
from __future__ import annotations

import pytest

from agience_chorus import _secrets

ALLOWED = ["https://api.example.com/v1"]


@pytest.mark.parametrize("url", [
    "https://api.example.com/v1",
    "https://api.example.com/v1/x",
    "https://API.EXAMPLE.COM/v1",
    "https://api.example.com:443/v1",
    "https://api.example.com/v1?x=1",
])
def test_what_the_credential_names_is_allowed(url):
    assert _secrets.endpoint_allowed(url, ALLOWED)


@pytest.mark.parametrize("url", [
    "https://api.example.com/v1/../../admin",
    "https://api.example.com/v1/./../admin",
    "https://api.example.com/v1%2f..%2fadmin",
    "https://api.example.com/v1/%2e%2e/admin",
    "https://evil.test@api.example.com/v1",
    "https://evil.test\\@api.example.com/v1",
    "https://api.exa\tmple.com/v1",
    "https://api.exampıe.com/v1",
    "  https://api.example.com/v1",
    "https://api.example.com/v1x",
    "https://api.example.com:8443/v1",
])
def test_anything_the_sender_would_read_another_way_is_refused(url):
    assert not _secrets.endpoint_allowed(url, ALLOWED)
