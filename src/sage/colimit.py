"""Record absorption — the colimit of records that are the same THING.

Split out of `src/junction/tekton_colimit.py` on 2026-08-25 under John's ruling. That module could
not import (`mantle_common` was never tracked), nothing referenced it, and it had no test. This is
its PURE half, which the original had already isolated behind an explicit banner: *"Everything with
side effects lives in the organon half below."* The organon half is at
`_scratch/lab/tekton-colimit/`, where it stays until its missing dependency is written.

**Not the same operation as `sage/condense.py`, which shares the vocabulary.** Both cite
*"Facet conducts, tekton condenses"* and both speak of a colimit, and they act at different times
on different things:

    condense.py   QUERY time   a reached SET      -> which condenser its shape already is
    colimit.py    STORE time   duplicate RECORDS  -> one junction per thing, sources absorbed

**Two identities, and this supplies the second.** A record is identified by where it came from
(`commit:<repo>:<sha>`); a thing by what it is OF (`thing:<kind>:<sha256(canonical)>`). Records
whose canonical body agrees derive the same thing-id and collapse on contact — no similarity
threshold, no model, no judgement call.

**No similarity matching here, deliberately.** Two records overlapping 94% may differ in the 6%
that matters, and a condensation that loses a distinction is worse than the duplication it removes.
This settles only what is provably one thing: identical canonical bodies. Near overlap needs a pass
that can raise a CONTRADICTION rather than silently pick — `corpus.near_duplicates` is the estimator
for that, and it is a different decision.

**The case it was built from**, measured on 71/dev: one merge — *"chorus stops importing ember"* —
landed in `agience-origin` and `agience-mantle` on 2026-08-03. Two artifacts, 1,534 characters each,
differing by exactly ONE line: the provenance header. The store held it twice because identity was
the identity of a RECORD. What was meant was one decision.
"""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from typing import NamedTuple

OPERATOR = "op.reduce.colimit"

#: The provenance header a captured commit carries: `**repo** · \`sha\` · author · date`. It is
#: the line that differs between two records of one merge, and it is exactly what must NOT
#: participate in the thing's identity — it says where this copy came from, not what it says.
_PROVENANCE_LINE = re.compile(r"^\*\*[^*]+\*\*\s*·\s*`[0-9a-f]+`\s*·.*$", re.MULTILINE)


class Junction(NamedTuple):
    """One thing, and the records that turned out to be it."""
    thing_id: str
    title: str
    canonical: str
    sources: list          #: the absorbed records, in the order seen


def canonical_body(content: str) -> str:
    """The record's text with its per-copy provenance removed — what the thing itself says.

    Whitespace is collapsed at the line level rather than wholesale: a body that differs only in
    trailing spaces is the same body, while indentation inside the message is content and stays.
    """
    stripped = _PROVENANCE_LINE.sub("", content or "")
    return "\n".join(ln.rstrip() for ln in stripped.splitlines() if ln.strip())


def thing_id(kind: str, canonical: str) -> str:
    """`thing:<kind>:<sha256>` — content-addressed, so two observers agree without conferring."""
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
    return f"thing:{kind}:{digest}"


def condense(records: list) -> list:
    """THE TEKTON. Records in, junctions out. Pure — no store, no network, no clock.

    A record is `{"id", "title", "content", "kind", "context"}`. Returns one :class:`Junction`
    per group of two or more records that are provably the same thing; a record that is the only
    one of its thing is left alone, because there is nothing to absorb and emitting a junction
    over a single record would add an artifact while removing none.
    """
    groups: dict[str, list] = defaultdict(list)
    for record in records:
        canon = canonical_body(record.get("content") or "")
        if not canon:
            continue
        groups[thing_id(record.get("kind") or "record", canon)].append((canon, record))

    out: list = []
    for tid, members in sorted(groups.items()):
        if len(members) < 2:
            continue
        canon = members[0][0]
        title = thing_title(m[1].get("title") or "" for m in members)
        out.append(Junction(tid, title, canon, [m[1] for m in members]))
    return out


#: A captured commit's title is `repo@sha: subject`. The prefix names the RECORD, not the thing.
_RECORD_PREFIX = re.compile(r"^[\w.-]+@[0-9a-f]{6,}:\s*")


def thing_title(titles) -> str:
    """The thing's own name, with every record's identity stripped out of it.

    Naming a junction after one of its copies is the same category error the thing-id exists to
    remove: `agience-mantle@08a37ae6: merge ...` records which repo happened to be read first,
    and the whole point is that the answer does not depend on that. What survives the prefix is
    the subject line — what the decision was actually called.
    """
    cleaned = {_RECORD_PREFIX.sub("", t).strip() for t in titles if t}
    cleaned.discard("")
    if not cleaned:
        return "(untitled)"
    # Shortest, so a title that merely embellishes another does not win on length.
    return min(cleaned, key=len)


def render(j: Junction) -> str:
    """The junction's body: what the thing says, then every record that said it.

    The sources are IN THE BODY and not only in edges, because the body is what `recall` reads
    and what a reader is shown. A junction that could not tell you it came from three repos would
    be a summary; carrying them makes it a junction.
    """
    lines = [j.canonical, "", "---", "", "## Recorded in", ""]
    for record in j.sources:
        ctx = record.get("context") or {}
        repo = ctx.get("repo") or "?"
        sha = (ctx.get("sha") or "")[:12]
        lines.append(f"- **{repo}** `{sha}` — artifact `{record['id']}`")
    lines += ["", f"_Condensed from {len(j.sources)} records by `{OPERATOR}`. "
                  f"Each source is archived, not deleted._"]
    return "\n".join(lines)
