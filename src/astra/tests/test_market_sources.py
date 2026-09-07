"""astra's ported market fetchers — the parts that are testable without a network.

Ported from beacon-market. These pin the properties a copy-paste would have quietly lost: the OHLCV
column order (part of the contract), that an unknown bar interval does not resolve, and that an
unparseable timestamp stays unknown rather than being fabricated.
"""
import pytest

from astra import market_sources as ms


def test_interval_seconds_known_values():
    assert ms.interval_seconds("15m") == 900
    assert ms.interval_seconds("1h") == 3600
    assert ms.interval_seconds("1d") == 86400


def test_unknown_interval_is_REFUSED_not_guessed():
    """A wrong bar width silently changes every downstream scale — τ and bf are measured off the bar
    clock — so a guess here would corrupt the measurement rather than fail."""
    with pytest.raises(ValueError, match="unknown interval"):
        ms.interval_seconds("7m")


def test_ohlcv_column_order_is_part_of_the_contract():
    """Order, not just membership: a downstream frame must build identically on any host."""
    assert ms.OHLCV_COLUMNS == ("ts", "open", "high", "low", "close", "volume")


def test_epoch_ms_to_iso_is_utc():
    out = ms._iso_utc_ms(1749648000000)
    assert out.startswith("2025-06-11T")
    assert out.endswith("+00:00")          # explicit UTC offset, never a naive local time


def test_gdelt_timestamp_parses_its_documented_shape():
    assert ms._iso_utc_gdelt("20260611T120000Z") == "2026-06-11T12:00:00Z"


@pytest.mark.parametrize("junk", ["", "nonsense", "20260611", "2026-06-11T12:00:00Z"])
def test_an_unrecognised_publish_time_stays_UNKNOWN(junk):
    """Returns "" rather than inventing a timestamp. A fabricated publish time would look like
    provenance and be wrong — worse than an absent one."""
    assert ms._iso_utc_gdelt(junk) == ""


def test_module_needs_neither_pandas_nor_requests():
    """The port dropped both on purpose: chorus ships httpx and not requests, and a persona is the
    wrong place to acquire pandas. If either reappears, the dependency crept back in."""
    import inspect
    src = inspect.getsource(ms)
    assert "import pandas" not in src and "import requests" not in src
    assert "import httpx" in src
