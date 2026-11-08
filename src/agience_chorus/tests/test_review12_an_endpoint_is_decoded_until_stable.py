"""Review 12: an endpoint's path is percent-decoded until it is stable before it is matched.

A path decoded once can still carry an encoded `..` (`%252e%252e` decodes to `%2e%2e`), which a
server that decodes again reads as a parent segment. The match decodes until nothing changes
(bounded), so what is compared is what any decoding sender or server will reach."""
from __future__ import annotations

import pytest

from agience_chorus._secrets import endpoint_allowed

ALLOWED = ["https://api.example.com/v1/"]


@pytest.mark.parametrize("url", [
    "https://api.example.com/v1/%252e%252e/admin",
    "https://api.example.com/v1/%25252e%25252e/admin",
    "https://api.example.com/v1/%252E%252E%252Fadmin",
    "https://api.example.com/v1/x/%252e%252e/%252e%252e/admin",
])
def test_a_path_encoded_twice_or_more_is_decoded_until_stable(url):
    assert not endpoint_allowed(url, ALLOWED)


def test_a_path_that_does_not_settle_within_the_bound_is_refused():
    from urllib.parse import quote
    seg = ".."
    for _ in range(12):                      # twelve layers of encoding: more than the bound
        seg = quote(seg, safe="")
    assert not endpoint_allowed("https://api.example.com/v1/" + seg + "/admin", ALLOWED)


def test_an_ordinary_path_under_the_named_one_still_matches():
    assert endpoint_allowed("https://api.example.com/v1/chat/completions", ALLOWED)
    assert endpoint_allowed("https://api.example.com/v1/a%20b", ALLOWED)
