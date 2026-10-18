# Changelog

All notable changes to `agience-chorus` are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.2.4] - 2026-10-17

### Changed
- A new card is added to the workspace once: its "created" event can arrive before the create request answers, and both added it.
- The Archived filter in a workspace or collection loads its archived artifacts from the server, counts them, and shows them read-only with Restore and Delete. Restore returns the card to the live list.
- Search's Advanced panel is applied: the tag, the type (now including Markdown and Plain text), Exact words, and a new option to search archived artifacts instead are written into the recall request. A filter with no search text says that filters narrow a search. Search results keep recall's order instead of the view's sort.
- Right-click "Assign to collections…" opens the same picker as the toolbar, and a card's collection indicator updates as soon as it is assigned.
- Removing a card from a workspace or collection keeps it removed: the card no longer came back from the workspace's own list, or, in a container's card window, from the cards that still listed it. Failed removals say so.
- A workspace opened as a card window says workspace in its labels and has a New card button that creates the card there.
- A collection's card window no longer shows archived cards the workspace still holds.
- A link to a workspace this account cannot open says so instead of opening the Inbox.
- The Help glossary describes artifacts, workspaces, collections, versions and archiving as they work now.
- A removal that archived the card (it was in no other workspace or collection) says so, and points to the Archived filter.
- New cards take numbered default titles ("Untitled Search 2") when the plain one is taken.
- A new card closed with no content and its default title is discarded.
- An edit still waiting on its autosave when a card window closes is saved rather than lost.
- The search panel shows the query it sent, with each applied filter as a chip, and Clear filters runs the search again.
- Double-clicking an archived card opens it read-only with Restore.
- Removing a card offers Undo.
- The multi-select toolbar's Drop reads "Remove from <workspace or collection>", and removes through the workspace, so a bulk removal stays removed.
- A card with a blank title shows the first line of its content.
- A card's Type in the Info panel is read-only.
- Every type inherits from Artifact (`*/*`): an artifact whose type nothing declares shows as an Artifact, never as a File, and an Agience or `+json` data type never falls to File. File is the catch-all for file formats only.
- A card's Collections panel lists every container it is in, workspaces included, and names a container it has not loaded by reading it.
- A container opened as a card shows its own name and description.
- The web app's build reads the builtin types from `agience-crystal/src/crystal/types`.
- The Inbox is the person's oldest own workspace, as Mantle provisions it, not their user id. With no workspace tab open, a new card was sent to the user id and refused as not found.
- Delete moves a card to Trash instead of deleting it: the confirmation says so, and a toast offers Undo and View Trash. A bulk delete announces once.
- Trash, from the trash button in the header: what you deleted in the last 30 days, when each goes for good, with Restore and Delete permanently. The Help glossary describes it.
- A new card closed untouched is still deleted for good, not moved to Trash.
- A new card is discarded on close only when the server still holds it empty under its default title, and an edited card is never a new card again. A card edited just before its window closed was deleted from a stale local copy.

### Added
- Sage declares the `text/x-wordnet` type once: its describer (`offer_template`, `field_source`) and its `offer`, which names a synset's lemmas as its names so Mantle indexes them.
- `sage.offer.declared_types()` and `declared_describer(ct)` read the types the personas declare in `<persona>/ui/<top>/<sub>/type.json`. Retrieval renders a hit with its type's declared describer, and reads a `type.<ct>` store row only for a type no type.json declares.

### Removed
- The search panel's precision slider, which recall never read, and its Custom filters block, which promised filtering recall does not do.

## [0.2.3] - 2026-10-12

### Changed
- An archived artifact opens read-only in the web app: its window offers no edit mode and no title or context editing, says it is archived, and has a Restore button; the side preview offers no Edit. The workspace store refuses any edit to an archived artifact other than restoring it, with a notice. Mantle answers such an edit with 404, and the card used to vanish with the edit lost.
- Archiving a card says so, with an Undo that restores it: an archived card leaves the workspace's listing.
- A failed save shows an error instead of silently reloading the workspace.
- Signing out as a service provider replaces the app with a "Signing out…" screen while the page goes to the IdP, so the workspace no longer shows in between.
- The open workspace's create button is labelled "New card", where it was an unlabelled "+" beside the tab bar's "+" for a new workspace.

## [0.2.2] - 2026-10-11

### Changed
- The header's Logout in the web app signs out through the auth provider, so as a service provider it also ends the IdP's session. It previously cleared only the app's own token and reloaded, and the IdP signed the person straight back in.
- As a service provider, signing out leaves the app's signed-in state as it is while the page goes to the IdP's `/logout`. Clearing it first started the app's own sign-in redirect, which replaced the navigation to `/logout` and left the IdP's session in place.

## [0.2.1] - 2026-10-11

### Changed
- Signing out of the web app when it is a service provider (`idpUri` set) also ends the IdP's session, through the IdP's `/logout`, so the next visit asks to sign in instead of signing straight back in.

## [0.2.0] - 2026-10-09

### Breaking

- Artifacts are stored with state `live` instead of `committed`. Operators registered by `aria` identity, `web_bff`, `fetch` and `astra.doc_index` use `live`, and `astra` reading units are always written `live`, with the draft/real distinction carried by their `condensed` and mass fields. Stored data and queries that use `committed` need updating.
- The minimum dependency versions are now `agience-prism>=0.1.4` and `agience-mantle>=0.1.3`.
- `POST /api/contact` in the `aria` web BFF requires the signed token from `GET /api/contact/nonce`, sent as `X-Agience-Challenge`. Tokens are signed with `BFF_NONCE_SECRET` and expire after 30 minutes. Requests without a valid token get 403. Over-limit requests get 429, and bodies over 16 KB get 413.
- `GET /stream/sessions` in `astra` now lists one source's sessions and needs a Bearer token that can read that source.
- `GET /healthz` in the `aria` web BFF no longer returns `lead_to` or `lead_from`.
- The `astra` `sync_source` result no longer includes `committed` or `indexed`. `market_ingest.commit_series` is removed.

### Added

- `agience_chorus._egress`, a shared outbound-fetch guard with `fetch`, `check_url`, `address_refused`, `host_refused` and `require_token_endpoint`. It uses only the standard library and travels inside bundles as a sibling module.

### Changed

- `lumen/reading/operator_respond.py` uses the installed instrument package instead of a workspace checkout on `sys.path`.
- `POST /api/chat` in the `aria` web BFF reads at most 64 KB of body and 2,000 characters per message. Messages beginning with `/` are answered with `refused: true` and are not passed to the responder. The responder runs in a worker thread, so other routes stay responsive during a reply.
- The reading responder in `lumen.reading.chat` keeps state per caller. Anonymous callers carry nothing between turns and cannot use `/use` or `/collections`.
- `op.fetch.get` in `astra` follows redirects itself, up to 5 hops, and checks each hop. Reading stops at the 5 MB cap, and all hops share one 20-second deadline.
- The `aria` chat view escapes quotes in text it renders.

### Security

- `op.fetch.get` is GET-only over `http` and `https`. It resolves the host and refuses it unless every address is public unicast. Loopback, private, link-local, CGNAT, multicast, reserved and IPv6-embedded IPv4 addresses are refused. Hosts written as numbers, `localhost` and private name suffixes are refused before any lookup. The connection goes to the address that was checked, with TLS still verified against the host name.
- OAuth token exchanges are allowed only to endpoints listed in `OAUTH_TOKEN_ENDPOINTS`, currently `https://oauth2.googleapis.com/token`. Endpoints read from caller-editable config are refused.
