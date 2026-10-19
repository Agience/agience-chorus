"""Reconciliation — several accounts of one event, compared fact by fact.

Each account is an artifact as its author wrote it. What it states is read off its content as
`Label: value` lines — the shape an incident form, an inspection sheet or meeting notes take — and
its narrative stays narrative. For each label the accounts state, the reconciliation says whether
they agree, where they differ (each version with the accounts behind it and the evidence those
accounts point to), and what only one account states. A person settles each difference; nothing
here decides between versions, and no account is ever changed.

It reads stated facts, deterministically. Extracting facts from free prose is a model's job, and
belongs to an operator built on an LLM connection; this one is exact about what it compares.

Pure: no I/O. `server.reconcile` reads the accounts and writes the result.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List

#: A stated fact: a short label, a colon, a value. A label longer than this, or of more words, is a
#: sentence that happens to hold a colon, not a label.
MAX_LABEL = 40
MAX_LABEL_WORDS = 5
_LINE = re.compile(r"^\s*[-*•]?\s*([^:\n]{1,%d}):\s*(.+?)\s*$" % MAX_LABEL)
RECONCILIATION_KIND = "reconciliation"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().rstrip(".;,").casefold()


@dataclass
class Account:
    id: str
    name: str
    content: str
    evidence: List[str] = field(default_factory=list)

    def facts(self) -> Dict[str, tuple]:
        """{normalized label: (label as written, value as written)}; the first statement of a label wins."""
        out: Dict[str, tuple] = {}
        for line in (self.content or "").splitlines():
            m = _LINE.match(line)
            if not m:
                continue
            label, value = m.group(1).strip(), m.group(2).strip()
            if not value or "http" in label.casefold() or len(label.split()) > MAX_LABEL_WORDS:
                continue
            out.setdefault(_norm(label), (label, value))
        return out


def reconcile(accounts: List[Account]) -> dict:
    """{"agreed": [...], "conflicts": [...], "single": [...], "accounts": n}."""
    by_label: Dict[str, Dict[str, dict]] = {}
    labels: Dict[str, str] = {}
    for a in accounts:
        for key, (label, value) in a.facts().items():
            labels.setdefault(key, label)
            version = by_label.setdefault(key, {}).setdefault(
                _norm(value), {"value": value, "accounts": [], "evidence": []})
            version["accounts"].append({"id": a.id, "name": a.name})
            version["evidence"] += [e for e in a.evidence if e not in version["evidence"]]
    agreed, conflicts, single = [], [], []
    for key in sorted(by_label, key=lambda k: labels[k].casefold()):
        versions = list(by_label[key].values())
        stated_by = sum(len(v["accounts"]) for v in versions)
        entry = {"label": labels[key], "versions": versions}
        if len(versions) > 1:
            conflicts.append(entry)
        elif stated_by > 1:
            agreed.append(entry)
        else:
            single.append(entry)
    return {"accounts": len(accounts), "agreed": agreed, "conflicts": conflicts, "single": single}


def _who(version: dict) -> str:
    return ", ".join(a["name"] for a in version["accounts"])


def report(result: dict, title: str) -> str:
    """The reconciliation as a person reads it."""
    lines = [f"# {title}", "", f"{result['accounts']} accounts compared, fact by fact. "
             "No account was changed; each difference is for a person to settle.", ""]
    lines.append("## Agreed")
    lines += [f"- **{e['label']}:** {e['versions'][0]['value']} — {_who(e['versions'][0])}"
              for e in result["agreed"]] or ["- (nothing stated by more than one account)"]
    lines += ["", "## In conflict"]
    for e in result["conflicts"]:
        lines.append(f"- **{e['label']}:**")
        for v in e["versions"]:
            ev = f"; evidence {', '.join(v['evidence'])}" if v["evidence"] else ""
            lines.append(f"  - \"{v['value']}\" — {_who(v)}{ev}")
    if not result["conflicts"]:
        lines.append("- (none)")
    lines += ["", "## Stated by one account"]
    lines += [f"- **{e['label']}:** {e['versions'][0]['value']} — {_who(e['versions'][0])}"
              for e in result["single"]] or ["- (none)"]
    return "\n".join(lines) + "\n"


def conflict_reason(entry: dict) -> str:
    return "The accounts differ: " + "; ".join(f"\"{v['value']}\" ({_who(v)})" for v in entry["versions"])
