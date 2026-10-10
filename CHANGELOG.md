# Changelog

All notable changes to `agience-chorus` are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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
