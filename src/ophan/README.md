# agience-server-ophan

Status: Live — energy, licensing and subscription tools are registered and implemented in
`server.py`.

**Domain**: Economic Logic — energy accounting, licensing, entitlements and commercial operations.

Value transfers, crypto/fiat rails, double-entry bookkeeping, reconciliation, budgeting and
performance metrics are not this domain; `server.py` states plainly that no payment or chain rails
exist anywhere in the workspace.

---

## Responsibility

Ophan is the economic operations layer. It **measures energy** (an artifact's standing heat, cooled
to the current frame) and **computes settlement** between the governing Origin and the producer; it
issues, renews, revokes and reports on **licenses and entitlements**; and it carries the
**subscription surface** (activation and plan changes, plus outbound payment tools that carry no
execution path yet).

It does **not** move money — settlement computes only.

---

## Tool Surface

### The energy surface

Eighteen tools (`send_payment`, `record_transaction`, `get_transaction`, `list_transactions`,
`fetch_statement`, `get_balance`, `reconcile_account`, `create_invoice`, `apply_payment`,
`run_report`, `get_price`, `get_market_data`, `track_wallet`, `get_portfolio`, `calculate_pnl`,
`track_resource_usage`, `get_metrics`, `calculate_budget`) do not exist in this surface, and none is
planned. The absence is recorded inline in `server.py` at the `# ── the energy surface` block, which
states the reason:

> the screen is the market — rates are measured, never configured.

`get_price` and `get_market_data` would be the configured-rate anti-pattern that block argues
against. What Ophan offers instead is energy, built and tested in `beam`:

| Tool | Status | Description |
|---|---|---|
| `get_energy` | Read an artifact's energy, realised value, and thermal state (the 2nd-law economy) |
| `settle_energy` | Compute the settlement split for an artifact's earned value (flat Origin fee) |

### Licensing & Commercial Operations

| Tool | Status | Description |
|---|---|---|
| `resolve_license_posture` | registered | Determine whether an organization falls inside the public self-host grant or needs a commercial license |
| `issue_license` | registered | Create and sign a license artifact from entitlement inputs or approved policy parameters |
| `renew_license` | registered | Extend, replace, or reissue an existing license artifact |
| `revoke_license` | registered | Revoke a license and record the resulting compliance event |
| `review_installation` | registered | Inspect installation state, activation status, and lease freshness |
| `record_usage_snapshot` | registered | Ingest or reconcile aggregate licensing and metering snapshots |
| `run_licensing_report` | registered | Produce entitlement, installation, renewal, or overage report artifacts |

### Subscriptions & payment

`server.py` also registers five more tools, in the subscriptions-and-payment surface. Two of them are **live** and write:

| Tool | Status | Description |
|---|---|---|
| `activate_subscription` | live | Writes a subscription artifact, pushes `_PLAN_LIMITS` to `/internal/gate/set-limits`, adds VU credits. |
| `update_subscription` | live | Plan change; same gate + credit path. |
| `create_checkout_session` | registered, no execution path | Outbound payment write; has no `op.pay.session` organon to execute through yet. |
| `create_portal_session` | registered, no execution path | As above. |
| `create_vu_topup` | registered, no execution path | As above. |

Billing is a distinct surface from energy: the subscription tools are live, separate from the
*financial tool* surface (transfers, ledger, market data) described above, which this workspace
does not implement.

Licensing tools are entitlement-gated. Base installation review and usage flows require an active licensing entitlement; issuance, renewal, revocation, and reporting require advanced licensing-operations entitlement.

---

## Artifact Types Owned

Five artifact types are not owned here: `transaction+json`, `account+json`, `invoice+json`,
`portfolio+json` and `market+json`. Nothing in the module can mint any of them — their producers
and readers (`record_transaction`, `reconcile_account`, `create_invoice`, `apply_payment`,
`get_portfolio`, `calculate_pnl`, `get_market_data`) do not exist in this surface.

`market+json` in particular would conflict with the design: it is a price-feed type, and Ophan's own
rule is that the screen is the market — rates are measured, never configured. Owning the artifact
while rejecting the mechanism that fills it would be a contradiction.

A ledger surface here needs its own decision.

Licensing-related artifacts should also be operationally owned by Ophan, as a small shared family. In practice, Ophan should back licensing artifacts such as license, entitlement, installation, usage, and licensing-event records through shared structured-data handling.

Current licensing artifact family:

- `application/vnd.agience.license+json`
- `application/vnd.agience.entitlement+json`
- `application/vnd.agience.license-installation+json`
- `application/vnd.agience.license-usage+json`
- `application/vnd.agience.license-event+json`

Canonical licensing-party identity should be represented by the general platform Organization
artifact, not by Ophan's own financial account artifact:

- `application/vnd.agience.organization+json`

---

## Credentials (BYOK)

Financial credentials are **Bring Your Own Key**, stored as encrypted user secrets in the platform —
never in environment variables.

There is no table of BYOK secret names for a financial-tool surface (`COINBASE_*`, `BINANCE_*`,
`ALPACA_*`, `PLAID_*`, `COINGECKO_API_KEY`) because that surface does not exist here; `server.py`
reads none of those names.

The BYOK **rule** is binding across the workspace: a financial credential is the user's, stored as an
encrypted secret, and never read from the environment.

The server reads no `AGIENCE_API_KEY` or `AGIENCE_API_URI` — a grep for both in `server.py` returns
nothing, and `.well-known/mcp.json` marks both "removed". Auth is a self-issued platform JWT signed
with the chorus service identity (`chorus.private.pem`). The environment it actually reads is
`MANTLE_URI`, `ORIGIN_URI`, `MCP_HOST`/`MCP_PORT`/`MCP_TRANSPORT`, `LOG_LEVEL` and
`STRIPE_PRICE_ID_*`.

**Stripe.** `STRIPE_SECRET_KEY` is not read anywhere; its only would-be consumers are the outbound
`Session.create` writes, which have no `op.pay.session` organon to execute through yet.
`STRIPE_WEBHOOK_SECRET` resolves from a stored secret artifact under a delegation and raises when it
cannot — a payments webhook that cannot verify a signature does not verify, and never falls through
to an unverified dispatch. Neither is read from the environment.

---

## Quick Start

```bash
pip install -e .
export MANTLE_URI=http://localhost:8081      # defaults to localhost:8081
export ORIGIN_URI=http://localhost:8080      # defaults to localhost:8080
python server.py
```

---

## Seed knowledge — none, and none is to be added

A prompt library would be an LLM surface even as only a heading in a README, because the next
person to read it would treat the absence as a gap to fill. This workspace does not do LLM
prompting or seed knowledge of that kind.

---

## Target Repo

`github.com/Agience/agience-server-ophan` (public)
