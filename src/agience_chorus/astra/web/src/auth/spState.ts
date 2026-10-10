// auth/spState.ts
//
// The `state` this app sends to Origin when it starts a sign-in as a service provider, and the
// check that a token returned in the URL fragment answers a sign-in this browser started.
//
// Without the check, any link of the form `/#access_token=<token>` would install that token as the
// session, so an attacker could sign a victim into the attacker's account (login CSRF).
//
// Stored in `localStorage`, not `sessionStorage`: the sign-in can finish in a different tab. When a
// new account verifies its email, the mailed link opens in a new tab, Origin restores the stashed
// `redirect_uri` and `state` there and hands the token back to this app in that tab, which has no
// `sessionStorage` from the tab that started. The TTL matches Origin's one-hour return window
// (`RETURN_TTL_MS` in origin's `web/app.js`); past it Origin no longer returns the person here.
//
// Several states may be pending at once (two tabs, or the redirect loop guard in `Login.tsx`
// retrying), so a short list is kept. The first state that matches completes the sign-in, and
// every pending state is then cleared: a sibling left live would let a crafted fragment carrying it
// replace the session for the rest of the hour.

const KEY = 'agience.sp_state';
const TTL_MS = 60 * 60 * 1000;
const MAX_PENDING = 5;

type Pending = { s: string; ts: number };

function readPending(now: number): Pending[] {
  let raw: unknown = null;
  try {
    raw = JSON.parse(localStorage.getItem(KEY) || '[]');
  } catch {
    raw = [];
  }
  if (!Array.isArray(raw)) return [];
  return raw.filter(
    (p): p is Pending =>
      !!p && typeof p.s === 'string' && p.s.length > 0 && typeof p.ts === 'number' &&
      now - p.ts >= 0 && now - p.ts < TTL_MS,
  );
}

function writePending(list: Pending[]): void {
  try {
    if (list.length === 0) localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, JSON.stringify(list));
  } catch {
    // Storage unavailable: nothing is pending, so no fragment token will be accepted.
  }
}

/** Generate and remember a fresh state for a sign-in about to start. */
export function issueSpState(now: number = Date.now()): string {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  const state = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
  writePending([...readPending(now), { s: state, ts: now }].slice(-MAX_PENDING));
  return state;
}

/**
 * True when `returned` is a live state this browser issued. A match clears every pending state,
 * so no state is accepted after a sign-in completes. Expired entries are dropped either way.
 */
export function consumeSpState(returned: string | null | undefined, now: number = Date.now()): boolean {
  const pending = readPending(now);
  const idx = returned ? pending.findIndex((p) => p.s === returned) : -1;
  if (idx === -1) {
    writePending(pending);
    return false;
  }
  writePending([]);
  return true;
}
