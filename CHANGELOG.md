# Changelog

All notable changes to `agience-chorus` are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.2.4] - 2026-10-17

### Changed
- Lumen's `synthesize` returns evidence and nothing else: it no longer runs the numeric forecaster (`op.reason`) on a series pasted into the question, a different job from answering from what the caller holds. The forecaster stays an operator of its own.
- A card created or updated in another tab arrives with its title: the change feed carries no title any more (it is sealed with the content), so the app completes each descriptor with an authorized read before showing it.
- A card view's save keeps what was written to the card while the view was open: each key the view changed takes the view's value, every other key keeps the stored one. Disarming a timer from its card wrote the view's copy back whole and erased Lumen's record of its runs.
- A workspace tab opened while the previous workspace was still loading shows its own cards. The previous workspace's list arrived after the switch and replaced them, so the Inbox tab could show another workspace's cards.
- A workflow step whose tool refused (a Transform passing on its tool's result, `isError` inside) fails the workflow, and its timer records the run as failed. A step naming a tool its persona does not have answered "Unknown tool" inside a result marked successful, and the workflow reported completion.
- Platform mail (plan receipts and usage warnings) is Iris's own operation (`/iris/platform-mail`), open to the chorus host's platform identity only. Ophan resolves the address and asks Iris; Iris obtains the platform-mail system delegation as itself and has the platform authorizer's secrets released sealed to its own key. Ophan invoked the email operator on Mantle (which serves no operations) under a delegation addressed to Mantle, which Iris refused, and the system principal held `read` on the secrets: no receipt or usage warning was ever sent.
- A workflow step, `chain_tasks` and Lumen's grounding call another persona with the caller's own token, not Lumen's delegation; every cross-persona step answered 401. A step whose result carries an error fails the workflow, and a timer records the run as failed (`timer_state.last_ok`); both were reported as successes.
- Workflow tool steps and `chain_tasks` call a persona by name (or a person's MCP server by id) through Crystal's `/personas` routes. They posted to `/artifacts/<name>/op/invoke`, which names no artifact, and every step answered 404. An MCP server card's resources are read the same way; its three operations that named a removed Mantle importer are gone.
- The Key card issues a key over the collections it names, read only or read and write, and can revoke it. It sent the retired `scopes` and `resource_filters`, which Mantle does not read, so every key made from a Key card reached nothing; and it had no way to revoke. An MCP client card's key is likewise a grant on the client's workspace.
- Card viewers open: a type's view is read from the persona that serves it, and the view's tools are called on that persona, through Crystal's `/personas` routes. Every `vnd.agience.*` viewer (Key, Chat, Account and the rest) said its server was not running, because the app looked the persona up as an MCP-server artifact and none exists. The Tools and Resources panels and the sidebar list the personas with their tools and resources, beside any MCP-server artifacts.
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
- The bundle check's control corrupts a copy of the tree instead of the shipped payloads, which other suites read while it runs.
- A workflow is built from operators, not tools: the builder offers the operators the person may invoke, grouped as the platform's, their own and ones shared with them; each step names its operator and is invoked through its grant. An argument naming an artifact is chosen with the app's picker and kept as a typed link from the workflow (`@link.<key>.<argument>`), shown on the step by the linked artifact's name; it can instead take what an earlier step returned. The recipes are the platform's own operators. A card that ran a tool directly offers to be rebuilt as steps.
- The app's picker offers the content types an argument accepts (collections when it names none), and answers with the role it was opened for and the chosen artifact's name.
- Arming a timer asks Lumen what its key must reach (`timer_reach`): its workspace and target, where it records and raises, and each operator and linked artifact of the workflow it runs. The person approves that list.
- A timer on a card made before steps were operators reaches the platform operator behind each tool it calls directly, so the platform's gate lets its key through.
- Running a tool or prompt on an MCP server a person added (Iris's `call_mcp_server`, `tools/call` and `prompts/get`) needs `invoke` on the server's card; seeing what it offers needs `read`. A card shared to be seen also let its reader run every tool on the server.
- Removing a step from a workflow (Lumen's `remove_workflow_step`, the builder's Remove) removes the links it kept to the artifacts it works on; the artifacts are untouched.
- A card's History names each reader by the name its owner gave the grant that reaches them, on the card or on a container it is in (an invitation's name is kept when it is claimed), instead of "Someone else" and an id. Only the owner reads the access log and lists grants, so nobody learns a name they did not give.
- A workspace has an Upload button beside New card: files chosen there arrive as a drop would bring them, so a phone, which cannot drag, can add a photo (its picker offers the camera). The "More" button beside it, which did nothing, is gone.
- Three controls that led nowhere are gone: "Send to AI Agent" on a multi-card selection (an alert saying it was coming), Settings' empty General tab, and the admin page's empty Integrations tab.
- The share dialog offers the `contributor` role: adds, and changes nothing of others.
- History and the collection dialog no longer show commits, which are not part of the model: each change is a new version of the same root. History shows the access record; the dialog, the collection's sharing.

### Added
- Lumen's `synthesize` grounds on Sage's new `retrieve` tool (op.retrieve) through Crystal, under the asker's own grants. Its corpus leg was dark in every deployment: no host ever wired the retrieval reach.
- Iris's `call_mcp_server` reaches an MCP server a person added: the card is read as the caller, only an HTTP endpoint is reached, through the egress guard (now with a guarded POST that follows no redirect), and the caller's credential is never sent; a server that needs one names a secret.
- Timers: a Timer card (Lumen) runs an artifact's operation — a workflow, an operator — every N minutes, daily, or once, and records each run. The owner arms it from the card, which issues the grant key it acts on over the timer's workspace; disarming revokes the key. Lumen keeps armed keys sealed with the node's chorus key (`LUMEN_TIMERS_DIR`). `schedule_action` creates a Timer card instead of refusing.
- An LLM connection card can be invoked: Lumen's `invoke_connection` reads the card on the caller's grant and has its key released for the one call through Mantle's `use` route, sealed to Lumen's own key and opened only at the call (the caller needs `invoke` on the card and the key, not `read`), sends the conversation to the model it names (Anthropic, OpenAI or Mistral) through the egress guard, and returns the reply. A card whose endpoint is not the provider's own address is refused, because the request carries the key. A platform connection is an ordinary card and key the platform grants; there is no separate resolution mode.
- Iris uses an authorizer's secrets, and a person's MCP server's secret, only as released for that card and sealed to Iris's own key (`agience_chorus._secrets`); it read them in plaintext on the caller's `read`. Lumen and Iris each sign their delegation exchange with their own key, so the secret is released to a proven persona.
- A workflow's Runs collection is made by the person building or scheduling it (saving it in the builder, `prepare_runs`, `schedule_action`), and a timer scheduled on it records there: a timer's key creates nothing top-level, so a workflow scheduled before its first run recorded its runs in the workspace.
- Every workflow run is a Run card (`vnd.agience.run+json`, with its view) in the workflow's Runs collection, made on its first run: status, and each step's status, output and error. A step's inputs can take what an earlier step returned (`$.previous`, `$.steps.<name>`, and a field inside either); the builder offers that as a choice on each input, lists the recent runs, and has a schedule record into the Runs collection. A step could take only the values fixed when it was built, and nothing showed what a run had done.
- The Transform type is called "Workflow" in the app, which is what a person looks for in New card.
- A workflow is built in its card. The Transform view is a builder: start from a recipe (reconcile accounts, answer from my notes, raise an Inbox item), pick a tool from any persona you can use, fill the form made from its own inputs, add steps in order, Run now (the tool's own answer, unwrapped), and create a Timer with failures to your Inbox. Lumen's `workflow_catalog` and `add_workflow_step` serve it. The view was read-only and pointed to a palette mounted nowhere.
- Lumen's `reconcile`: several accounts of one event compared by the facts they state (`Label: value`); writes what all agree on, where they differ (each version with its accounts and evidence) and what only one states, and raises each difference as an Inbox item. No account is changed.
- Inbox items: an Inbox item card (Lumen, `vnd.agience.inbox-item+json`) holds what needs a person — why, what it came from, and optionally an action — and moves new → triaged → resolved, each move recorded with who made it. `raise_item` places one on the caller's own credential; `set_item_state` moves it; `approve_item` runs its action on the approver's credential, records what it returned, and resolves it (an action that fails leaves it open). A Timer with `inbox_to` raises a failed run there, carrying the routine as its action so approving reruns it; arming a timer issues its key over that place too.
- A card's window has a History panel: what was added to and removed from what the card holds (its commits), for anyone who can read it, and its access log — who reached it (a person, a key, or a persona or client acting for a person), what they did, allowed or denied — for those who administer it.
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
