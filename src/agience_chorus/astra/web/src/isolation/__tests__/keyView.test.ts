// The Key artifact's view (seraph `vnd.agience.key+json`), run as the host runs it: its collections
// are chosen with the app's picker (BUG-075), and its expiry form offers what the host accepts.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
// @ts-expect-error jsdom ships no declarations; this test uses its JSDOM constructor alone.
import { JSDOM } from 'jsdom';
import { describe, expect, it } from 'vitest';

const VIEW = resolve(__dirname, '../../../../../seraph/ui/application/vnd.agience.key+json/view.html');

type Sent = { jsonrpc: '2.0'; id?: number; method: string; params?: Record<string, unknown> };

function openView() {
  const sent: Sent[] = [];
  // jsdom runs no module scripts; the view's one script is run as a classic one, which it reads the same.
  const html = readFileSync(VIEW, 'utf-8').replace('<script type="module">', '<script>');
  const dom = new JSDOM(html, {
    runScripts: 'dangerously',
    beforeParse(window: Window) {
      // The view talks to its host through `parent.postMessage`; here the parent is the window.
      window.postMessage = ((msg: Sent) => { sent.push(msg); }) as typeof window.postMessage;
    },
  });
  const win = dom.window as Window & typeof globalThis;
  const deliver = (data: unknown) => win.dispatchEvent(new win.MessageEvent('message', { data }));
  return { dom: dom as { window: Window }, sent, deliver, doc: win.document };
}

describe('the Key view', () => {
  it('asks the host for each collection, lists what was picked, and makes the key over those', async () => {
    const { sent, deliver, doc, dom } = openView();
    (doc.getElementById('addCollectionBtn') as HTMLButtonElement).click();
    const ask = sent.find((m) => m.method === 'ui/open-picker');
    expect(ask?.params).toMatchObject({ role: 'key-collection', action: 'admin' });

    deliver({ jsonrpc: '2.0', method: 'ui/notifications/picker-result',
      params: { role: 'key-collection', artifact_id: 'col-1', title: 'Pilot notes' } });
    deliver({ jsonrpc: '2.0', method: 'ui/notifications/picker-result',
      params: { role: 'key-collection', artifact_id: 'col-1', title: 'Pilot notes' } });
    deliver({ jsonrpc: '2.0', method: 'ui/notifications/picker-result',
      params: { role: 'some-other-role', artifact_id: 'col-x' } });
    const items = [...doc.querySelectorAll('#pickedCollections li')].map((li) => li.querySelector('span')?.textContent);
    expect(items).toEqual(['Pilot notes']);

    // The request goes to the host; its answer (which would show the secret) is not needed here.
    void (dom.window as unknown as { handleGenerate: () => Promise<void> }).handleGenerate();
    await new Promise((r) => setTimeout(r, 0));
    const create = sent.find((m) => m.method === 'tools/call' && m.params?.name === 'create_api_key');
    expect(create?.params?.arguments).toMatchObject({ collections: ['col-1'], actions: ['read'],
                                                      collection_titles: { 'col-1': 'Pilot notes' } });
    expect(create?.params?.arguments).not.toHaveProperty('agent');
  });

  it('refuses to make a key over no collection', async () => {
    const { sent, doc, dom } = openView();
    await (dom.window as unknown as { handleGenerate: () => Promise<void> }).handleGenerate();
    expect(sent.some((m) => m.params?.name === 'create_api_key')).toBe(false);
    expect(doc.body.textContent).toContain('Add at least one collection the key reaches.');
  });

  it('offers 1 to the most days the host accepts, and says so', () => {
    const { doc } = openView();
    const days = doc.getElementById('inputDays') as HTMLInputElement;
    expect(Number(days.max)).toBeGreaterThan(0);
    expect(doc.querySelector('label[for="inputDays"]')?.textContent).toContain(`1 to ${days.max}`);
    expect(doc.getElementById('inputCollections')).toBeNull();
  });
  it('shows an issued Key from its own fields, with its hint and never a token', () => {
    const { deliver, doc } = openView();
    deliver({ jsonrpc: '2.0', method: 'ui/notifications/tool-result', params: { content: [{ type: 'text',
      text: JSON.stringify({ artifact_id: 'k1', state: 'live', context: { title: 'CI', collections: ['c-1'],
        collection_titles: { 'c-1': 'Notes' }, actions: ['read'], agent: 'agent-1',
        expires_at: '2026-12-01T00:00:00Z', token_hash: 'h', hint: 'wxyz' } }) }] } });
    expect(doc.getElementById('keyScope')?.textContent).toBe('Notes');
    expect(doc.getElementById('keyAgent')?.textContent).toBe('agent-1');
    expect(doc.getElementById('keyHint')?.textContent).toBe('…wxyz');
    expect(doc.getElementById('createSection')?.classList.contains('hidden')).toBe(true);
    expect(doc.getElementById('storedSection')?.classList.contains('hidden')).toBe(false);
  });

  it('shows an archived Key as revoked, and revoking asks the host to archive the hosted Key', async () => {
    const { sent, deliver, doc, dom } = openView();
    deliver({ jsonrpc: '2.0', method: 'ui/notifications/tool-result', params: { content: [{ type: 'text',
      text: JSON.stringify({ artifact_id: 'k1', state: 'archived', context: { token_hash: 'h', hint: 'wxyz' } }) }] } });
    expect(doc.getElementById('revokedSection')?.classList.contains('hidden')).toBe(false);
    void (dom.window as unknown as { handleRevoke: () => Promise<void> }).handleRevoke();
    await new Promise((r) => setTimeout(r, 0));
    expect(sent.find((m) => m.params?.name === 'delete_api_key')?.params?.arguments).toEqual({});
  });
});
