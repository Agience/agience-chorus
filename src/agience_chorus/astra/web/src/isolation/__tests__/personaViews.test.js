/**
 * Persona view templates (`agience_chorus/<persona>/ui/**\/view.html`) render artifact data with
 * innerHTML inside the McpAppHost iframe. Script in a view drives the host bridge, so artifact
 * fields must land as text: never as a new element, and never as an attribute that closes the one
 * it was written into.
 *
 * Every view is swept. Each is loaded in its own jsdom window, sent an artifact whose every field
 * holds a payload that breaks out of element content and of single- and double-quoted attributes,
 * rendered in view mode and (where the view has one) edit mode, and then checked for handler
 * attributes, injected elements, and executed script.
 *
 * PERSONA_VIEWS_ROOT points the sweep at another copy of the tree.
 */

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { describe, expect, it } from 'vitest';
import { JSDOM, VirtualConsole } from 'jsdom';

// Vitest runs from the web app root: <agience_chorus>/astra/web.
const VIEWS_ROOT = process.env.PERSONA_VIEWS_ROOT || join(process.cwd(), '..', '..');

function findViews(root) {
  const found = [];
  for (const persona of readdirSync(root)) {
    const uiDir = join(root, persona, 'ui');
    let isDir = false;
    try {
      isDir = statSync(uiDir).isDirectory();
    } catch {
      isDir = false;
    }
    if (!isDir) continue;
    const walk = (dir) => {
      for (const name of readdirSync(dir)) {
        const path = join(dir, name);
        if (statSync(path).isDirectory()) walk(path);
        else if (name === 'view.html') found.push(path);
      }
    };
    walk(uiDir);
  }
  return found.sort();
}

const MARK = 'PWNMARK';
// One breakout per payload: combined, a quote meant for one context can swallow the others.
const PAYLOADS = {
  'double-quoted attribute': `${MARK}" onmouseover="window.__pwned=1" x="`,
  'single-quoted attribute': `${MARK}' onfocus='window.__pwned=1' y='`,
  'element content': `${MARK}<img src="x" onerror="window.__pwned=1"><script>window.__pwned=1</script>`,
};

function payloadContext(p) {
  const flat = [
    'title', 'name', 'description', 'platform', 'relay_url', 'provider', 'model', 'tier', 'account',
    'notes', 'question', 'answer', 'symbol', 'interval', 'source', 'status', 'state', 'severity',
    'compliance_state', 'invoice_number', 'issuer', 'recipient', 'total', 'currency', 'amount',
    'balance', 'account_type', 'subject_card_id', 'signer_card_id', 'card_hash', 'signature_b64',
    'algorithm', 'prompt_name', 'evaluator', 'endpoint', 'url', 'client_id', 'kind', 'subtype',
    'type_', 'from_account', 'to_account', 'tx_hash', 'total_value', 'overall_score', 'overall_max',
  ];
  const ctx = Object.fromEntries(flat.map((k) => [k, p]));
  return {
    ...ctx,
    host: { scope: p, operator: p, facet_uri: p, origin_uri: p },
    stream: { server_url: p, language_code: p, target_content_type: p, sessions: [p] },
    connection: { url: p },
    client: { name: p },
    api_key: { id: p, preview: p, is_active: true },
    redirect_uris: [p],
    servers: [p],
    scopes: [p],
    run: { type: p, tool: p, server: p, url: p },
    rate_limits: { requests_per_minute: p, tokens_per_minute: p, tokens_per_day: p },
    capabilities: { max_context_tokens: p },
    credentials_ref: { resolution: p, secret_id: p },
    criteria: [{ name: p, notes: p, score: p, max_score: p }],
    candles: [{ o: p, h: p, l: p, c: p }],
    holdings: [{ symbol: p, quantity: p, current_price: p, market_value: p }],
    line_items: [{ description: p, quantity: p, amount: p }],
    sources: [{ card_id: p, excerpt: p }],
    arguments: [{ name: p, description: p, required: true }],
    transport: { type: 'http', well_known: p, command: p, cwd: p, args: [p], env: { [p]: p } },
    key: { api_key_id: p, scopes: [p] },
    chat: {
      messages: [{ role: 'user', content: p }, { role: 'assistant', content: p }],
      tool_calls: [{ name: p, arguments: { a: p }, result: p }],
    },
  };
}

function loadView(path) {
  // Module scripts are run as classic scripts: jsdom does not execute type="module".
  const html = readFileSync(path, 'utf8').replace(/<script type="module">/g, '<script>');
  const dom = new JSDOM(html, {
    runScripts: 'dangerously',
    url: 'https://view.invalid/',
    // Script errors inside a view stay inside its window; the checks below read the DOM.
    virtualConsole: new VirtualConsole(),
    beforeParse(window) {
      // A top-level jsdom window is its own parent. Requests a view posts to its host go nowhere
      // here rather than coming back as replies the view would read as the host's.
      window.postMessage = () => {};
      window.requestAnimationFrame = (cb) => setTimeout(cb, 0);
      Object.defineProperty(window.navigator, 'clipboard', { value: { writeText: async () => {} } });
    },
  });
  return dom.window;
}

function sendArtifact(window, payload) {
  const context = payloadContext(payload);
  const artifact = {
    artifact_id: 'art-1',
    id: 'art-1',
    description: payload,
    context,
    content: payload,
  };
  const text = JSON.stringify(artifact);
  window.dispatchEvent(
    new window.MessageEvent('message', {
      data: { jsonrpc: '2.0', method: 'ui/notifications/tool-result', params: { content: [{ type: 'text', text }] } },
    }),
  );
  window.dispatchEvent(new window.MessageEvent('message', { data: { type: 'artifact', artifact } }));
}

function injected(window) {
  const doc = window.document;
  const handlers = Array.from(doc.querySelectorAll('[onmouseover], [onfocus], [onerror]')).map(
    (el) => el.outerHTML.slice(0, 120),
  );
  const images = doc.querySelectorAll('img[src="x"]').length;
  const scripts = Array.from(doc.querySelectorAll('script')).filter((s) =>
    s.textContent.includes('window.__pwned=1'),
  ).length;
  return { handlers, images, scripts, pwned: window.__pwned === 1 };
}

const views = findViews(VIEWS_ROOT);

describe('persona view templates', () => {
  it('finds the persona views', () => {
    expect(views.length).toBeGreaterThanOrEqual(20);
  });

  describe.each(views.map((path) => [relative(VIEWS_ROOT, path), path]))('%s', (_name, path) => {
    it('every esc() escapes & < > " and \'', () => {
      const source = readFileSync(path, 'utf8');
      const window = loadView(path);
      if (!/function esc\(/.test(source)) return;
      expect(typeof window.esc).toBe('function');
      expect(window.esc(`&<>"'`)).toBe('&amp;&lt;&gt;&quot;&#39;');
      window.close();
    });

    it.each(Object.entries(PAYLOADS))('renders a %s breakout as text only', async (_kind, payload) => {
      const window = loadView(path);
      sendArtifact(window, payload);
      await new Promise((resolve) => setTimeout(resolve, 0));
      const viewMode = injected(window);

      let editMode = { handlers: [], images: 0, scripts: 0, pwned: false };
      if (typeof window.toggleEdit === 'function') {
        try {
          window.toggleEdit();
        } catch {
          // A view whose edit mode cannot open with this artifact has nothing more to render.
        }
        await new Promise((resolve) => setTimeout(resolve, 0));
        editMode = injected(window);
      }

      window.close();

      expect({ viewMode, editMode }).toEqual({
        viewMode: { handlers: [], images: 0, scripts: 0, pwned: false },
        editMode: { handlers: [], images: 0, scripts: 0, pwned: false },
      });
    });
  });

  it('every view that renders artifact fields rendered the payload as text', async () => {
    // A view that threw before rendering would pass the check above without having been tested.
    const silent = [];
    for (const path of views) {
      const window = loadView(path);
      sendArtifact(window, PAYLOADS['element content']);
      await new Promise((resolve) => setTimeout(resolve, 0));
      if (typeof window.toggleEdit === 'function') {
        try {
          window.toggleEdit();
        } catch {
          // see above
        }
        await new Promise((resolve) => setTimeout(resolve, 0));
      }
      const doc = window.document;
      const asText = doc.body.textContent.includes(MARK) ||
        Array.from(doc.querySelectorAll('input, textarea')).some((el) => el.value.includes(MARK));
      if (!asText) silent.push(relative(VIEWS_ROOT, path));
      window.close();
    }
    // Views that show no artifact field this payload reaches. Kept explicit so a view that stops
    // rendering is noticed.
    expect(silent).toEqual([]);
  });
});
