"""Several accounts of one event, reconciled fact by fact: what all agree on, where they differ (with
the accounts and evidence behind each version), what only one states — and each difference raised
for a person to settle. No account is changed.

2026-10-19: use case 11 (reconciling several accounts of one event) had no reconciliation operator.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agience_chorus.lumen import inbox as I
from agience_chorus.lumen import reconcile as R

from .test_chain_and_feedback import MockResponse

_spec = importlib.util.spec_from_file_location("chorus_lumen_server_reconcile",
                                               Path(__file__).resolve().parent.parent / "server.py")
L = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(L)

ANA = R.Account("a1", "Ana", "Time: 14:05\nLocation: Gate 3\nInjured: none\nThe alarm went off first.", ["photo-1"])
BEN = R.Account("b1", "Ben", "- Time: 14:05.\n- Location: gate 3\nWeather: rain")
CAL = R.Account("c1", "Cal", "Time: 14:20\nLocation: Gate 3", ["log-7"])


def test_facts_are_the_stated_label_value_lines_and_narrative_stays_narrative():
    assert ANA.facts() == {"time": ("Time", "14:05"), "location": ("Location", "Gate 3"),
                           "injured": ("Injured", "none")}
    assert R.Account("x", "x", "See https://example.com/report\nA long sentence that happens to have: a colon in it somewhere far").facts() == {}


def test_agreement_conflict_and_single_statements_are_told_apart():
    out = R.reconcile([ANA, BEN, CAL])
    assert out["accounts"] == 3
    assert [e["label"] for e in out["agreed"]] == ["Location"], "case and punctuation do not make a difference"
    (time,) = out["conflicts"]
    assert time["label"] == "Time"
    by_value = {v["value"]: v for v in time["versions"]}
    assert [a["name"] for a in by_value["14:05"]["accounts"]] == ["Ana", "Ben"]
    assert by_value["14:05"]["evidence"] == ["photo-1"] and by_value["14:20"]["evidence"] == ["log-7"]
    assert sorted(e["label"] for e in out["single"]) == ["Injured", "Weather"]


def test_the_report_names_each_version_and_who_holds_it():
    text = R.report(R.reconcile([ANA, BEN, CAL]), "Reconciliation of the gate incident")
    assert "## In conflict" in text and '"14:20" — Cal; evidence log-7' in text
    assert "**Location:** Gate 3 — Ana, Ben, Cal" in text
    assert R.conflict_reason(R.reconcile([ANA, CAL])["conflicts"][0]).startswith("The accounts differ:")


# ── the tool ──────────────────────────────────────────────────────────────────────────────────
class Store:
    def __init__(self):
        self.docs = {
            "coll": {"id": "coll", "context": json.dumps({"title": "Gate incident"})},
            "a1": {"id": "a1", "context": json.dumps({"title": "Ana", "evidence": ["photo-1"]}), "content": ANA.content},
            "b1": {"id": "b1", "context": json.dumps({"title": "Ben"}), "content": BEN.content},
            "c1": {"id": "c1", "context": json.dumps({"title": "Cal", "evidence": ["log-7"]}), "content": CAL.content},
        }
        self.created, self.patched = [], []

    def client(self):
        store = self

        class _C:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, headers=None, params=None, **kw):
                if url.endswith("/coll/children"):
                    return MockResponse({"items": [store.docs[k] for k in ("a1", "b1", "c1")]})
                doc = store.docs.get(url.rsplit("/", 1)[-1])
                return MockResponse(doc or {}, 200 if doc else 404)

            async def post(self, url, headers=None, json=None, **kw):
                store.created.append(json)
                return MockResponse({"id": f"new-{len(store.created)}"}, 201)
        return _C


@pytest.fixture
def person():
    tok = L._auth.request_user_token.set("delegation-for-me")
    try:
        with patch.object(L, "_get_delegation_user_id", lambda: "me-1"):
            yield
    finally:
        L._auth.request_user_token.reset(tok)


@pytest.mark.asyncio
async def test_reconciling_writes_one_record_and_raises_each_difference_for_a_person(person):
    store = Store()
    with patch.object(L.httpx, "AsyncClient", store.client()):
        out = json.loads(await L.reconcile("coll", inbox_to="inbox-1"))
    assert (out["accounts"], out["agreed"], out["conflicts"], out["single"]) == (3, 1, 1, 2)
    record, item = store.created
    assert record["container_id"] == "coll" and json.loads(record["context"])["kind"] == "reconciliation"
    assert "Reconciliation of Gate incident" in record["content"]
    assert item["container_id"] == "inbox-1" and item["content_type"] == I.ITEM_TYPE
    ctx = json.loads(item["context"])
    assert ctx["title"] == "Settle: Time" and ctx["item"]["evidence"][0] == "new-1"
    assert {"a1", "b1", "c1", "photo-1", "log-7"} <= set(ctx["item"]["evidence"])
    assert out["inbox_items"] == ["new-2"]


@pytest.mark.asyncio
async def test_one_account_is_not_a_reconciliation(person):
    store = Store()

    class One(store.client()):
        async def get(self, url, **kw):
            if url.endswith("/coll/children"):
                return MockResponse({"items": [store.docs["a1"]]})
            return await super().get(url, **kw)
    with patch.object(L.httpx, "AsyncClient", One):
        out = json.loads(await L.reconcile("coll"))
    assert "needs two or more" in out["error"] and store.created == []
