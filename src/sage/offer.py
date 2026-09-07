"""The offer — what an artifact advertises about itself, projected from its type's template.

This lives in sage rather than ember because it renders — it turns an artifact into the line that
describes it — and sage owns `op.describe.*`; a renderer belongs in the persona, not the runner.

`offer(type_artifact, artifact)` renders the type's `offer_template` from fields the artifact
already carries. That is the whole operation: a deterministic projection, never a composition.
There is no model, no generation, no invention: an offer states what the artifact is, using values
read from it. If a required field is missing the offer is refused and the reason reported — an
offer naming a field that could not be read is a fabrication, and a fabricated advertisement is
worse than no advertisement because retrieval will act on it.

This is not `describe.py`. That module extracts the keyed representation (lemmas, symbols) — the
dictionary arm. This one produces the `context` an artifact advertises — the offer/needs arm. They
run on the same artifact and neither replaces the other.

## What executes and what does not

  offer_template   machine-executable. "{title}: {summary}" — a format over field names.
  context_schema   machine-executable. `required` decides refusal; `properties` names the fields.
  for-ai           not executable, deliberately. It is Alpaca-shaped guidance (cuddler.dev's
                   standard) telling an agent — or a node meeting an unknown type — what the type
                   is and how each field is obtained. Prose cannot be executed; treating it as if
                   it could is how a model gets reintroduced. It is carried, surfaced, and never
                   interpreted by this module.

## Optional fields are omitted, not blanked

`"{title}: {summary}"` with no summary renders `"Hercule Poirot"`, not `"Hercule Poirot: "`. A
dangling separator asserts an empty value where there is simply no value — the same
absence-encoded-as-a-value defect that has bitten this codebase five times (`ic = 0.0`,
`signature("")`, `K_signal = 0`, `fit_error = NaN`, silent truncation).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# `{field}` in an offer_template. Deliberately the only syntax understood: no expressions, no
# conditionals, no nesting. A template language is a program, and a program in a data field is a
# place for arbitrary logic to hide.
_FIELD = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

# Rendered when a template's separator would dangle after an omitted optional field.
_TRAILING_SEP = re.compile(r"[\s:;,\-—(]+$")
_EMPTY_PARENS = re.compile(r"\s*\([^)]*\{\}[^)]*\)")


class OfferRefused(Exception):
    """A required field could not be read. Carries which one, so the caller can act or report.

    Never caught to substitute a placeholder: the refusal is the finding. An artifact whose required
    fields are unreadable is not describable yet, and saying so is the honest answer."""

    def __init__(self, artifact_id: str, missing: List[str], content_type: str):
        self.artifact_id, self.missing, self.content_type = artifact_id, missing, content_type
        super().__init__("%s (%s): required field(s) unreadable: %s"
                         % (artifact_id, content_type, ", ".join(missing)))


# ── format is not type ──────────────────────────────────────────────────────────────────────
# `content_type` says how the bytes are laid out. It says nothing about whether the data is an
# article, a memo, a table or a changelog — `application/json` has exactly the same problem.
# Dispatching a describer on the format alone is a category error that happens to work only while a
# format carries one kind of thing: most `text/markdown` rows in the corpus are homogeneous wiki
# articles, but a memo can carry the same content type and no title, and it did not fail for want of
# a title — it is a different type wearing the same format.
#
# Type definitions are discovered, not authored: a type definition is a colimit over artifacts that
# share structure, where the members are the artifacts, the generator is the definition
# (`context_schema` + `offer_template`), and the morphism is how each member's fields map onto it.
# Matching an unknown artifact against known definitions is asking which colimit it joins. A
# hand-written table of known types is a seed vocabulary — a bootstrap, compiled in and replicating
# with the code — not the answer.
#
# When that colimit is built, it must be taken over declared field structure, never over format
# similarity: two markdown files sharing a heading layout are not the same type, and a colimit taken
# over surface form would rediscover "these are both markdown" and call it a discovery.
DATA_TYPE_KEY = "data_type"


def data_type(artifact: Dict[str, Any]) -> Optional[str]:
    """The artifact's data type, or None if it has never been resolved.

    Explicit only — this function does not guess. An artifact that has not been matched to a type
    definition has no data type, and saying so is the honest answer; inferring one from the format
    would re-create the conflation this exists to remove."""
    v = artifact.get(DATA_TYPE_KEY)
    return str(v) if v not in (None, "", [], {}) else None


def describer_key(artifact: Dict[str, Any]) -> str:
    """Which type definition describes this artifact: its data type if resolved, else its format.

    The format fallback is a bootstrap, not the design: it is correct while a format carries one
    kind of thing and silently wrong the moment it does not — which is exactly why `offer()` refuses
    rather than improvises when the fields do not fit. A refusal here means "this artifact is not of
    the type I assumed", and that is a finding worth surfacing, not an error to suppress."""
    return data_type(artifact) or str(artifact.get("content_type") or "")


def template_fields(template: str) -> List[str]:
    """Field names a template references, in order of appearance."""
    return _FIELD.findall(template or "")


def _resolve_path(artifact: Dict[str, Any], path: str) -> Optional[Any]:
    """Follow a dotted path — `lemmas.0`, `lemmas.1:`, `context.name`. Still a lookup, not a
    computation: it only reads what is already there, one declared hop at a time.

    A path segment is a dict key, a list index (`0`), or a list slice (`1:`, `:3`, `2:5`). Any
    hop that does not resolve returns None — the honest "not present", never a guess."""
    cur: Any = artifact
    for seg in path.split("."):
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(seg)
        elif isinstance(cur, (list, tuple)):
            try:
                if ":" in seg:
                    a, _, b = seg.partition(":")
                    cur = list(cur[(int(a) if a else None):(int(b) if b else None)])
                else:
                    cur = cur[int(seg)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return cur


def _value(artifact: Dict[str, Any], field: str,
           field_source: Optional[Dict[str, str]] = None) -> Optional[Any]:
    """Read one offer field from the artifact. A lookup, never a computation.

    The derivation is declared by the type, not hardwired here: `field_source` maps a template
    field to a dotted path into the artifact (`{"lemma": "lemmas.0", "alt": "lemmas.1:"}`), and it
    lives on the type artifact — the definition says how its offer projects from the data, which is
    the colimit, not a rule baked into this reader. Absent a source, the field is a flat key. This is
    what lets a row carrying `lemmas` rather than `lemma` resolve a `lemma` field under its declared
    name instead of being refused for a value that was sitting right there.

    Empty string, empty list and empty dict all read as absent — an artifact carrying `title: ""`
    has no title, and rendering it as one would advertise a document with an empty name."""
    src = (field_source or {}).get(field)
    v = _resolve_path(artifact, src) if src else artifact.get(field)
    if v is None or v == "" or v == [] or v == {}:
        return None
    return v


def _render_value(v: Any) -> str:
    """One field's string form. Lists join with ', ' — an `alt` of several lemmas reads as a list
    of alternatives, which is what the wordnet template's `(also: {alt})` means."""
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v if x not in (None, ""))
    return str(v)


def offer(type_artifact: Dict[str, Any], artifact: Dict[str, Any]) -> str:
    """Render this artifact's offer from its content type's template.

    Raises `OfferRefused` if any field the type's `context_schema.required` names is unreadable.
    Optional fields simply drop out, taking their separator with them."""
    # The data type if it has been resolved, else the format. See `describer_key`.
    ct = describer_key(artifact) or str(type_artifact.get("declares") or "")
    tmpl = type_artifact.get("offer_template")
    if not tmpl:
        # A type with no template genuinely cannot be described — a structural gap, not a data one.
        raise OfferRefused(str(artifact.get("id")), ["<offer_template>"], ct)

    # There is no hardwired required-field gate: the refusal comes from the render rather than from
    # a `context_schema.required` list, so an artifact whose information is present under a name the
    # type declares (`lemmas` vs `lemma`) is not refused for a named field being absent. An artifact
    # that resolves no template field has nothing to advertise; one that resolves any does. The data
    # decides.
    field_source = type_artifact.get("field_source") or {}
    out = tmpl
    resolved = 0
    for field in template_fields(tmpl):
        v = _value(artifact, field, field_source)
        if v is not None:
            resolved += 1
        out = out.replace("{%s}" % field, _render_value(v) if v is not None else "{}")
    if resolved == 0:
        # Every field was absent — the artifact advertises nothing of this type. That is the
        # information deciding, not a hardcoded contract refusing.
        raise OfferRefused(str(artifact.get("id")), template_fields(tmpl), ct)

    # Optional fields that dropped out: remove the punctuation that was holding their place,
    # rather than leaving it to assert an empty value.
    out = _EMPTY_PARENS.sub("", out)
    out = out.replace("{}", "")
    out = _TRAILING_SEP.sub("", out)
    return " ".join(out.split()).strip()


def offer_or_none(type_artifact: Dict[str, Any],
                  artifact: Dict[str, Any]) -> Tuple[Optional[str], Optional[OfferRefused]]:
    """`offer()`, but returning the refusal instead of raising — for bulk passes that must record
    every refusal rather than stopping at the first. The refusal is returned, not swallowed: a
    caller that discards it silently converts "cannot describe" into "no offer"."""
    try:
        return offer(type_artifact, artifact), None
    except OfferRefused as e:
        return None, e


def guidance(type_artifact: Dict[str, Any], field: Optional[str] = None) -> List[Dict[str, str]]:
    """The type's agent-readable `for-ai` guidance — root level, or for one field.

    Surfaced, never interpreted. This is what lets a node meeting an unknown content type learn
    what describing it means instead of falling back to the generic describer and holding the
    vertex blind."""
    if field is None:
        return list(type_artifact.get("for-ai") or [])
    return list((type_artifact.get("field_guidance") or {}).get(field) or [])
