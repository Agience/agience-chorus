// The workflow artifact's view (lumen `vnd.agience.transform+json`), run as the host runs it: its
// steps show once their operators and linked items are read in the person's session (BUG-053,
// BUG-057), and an answer meant for an earlier view of the card never settles a request of this one.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
// @ts-expect-error jsdom ships no declarations; this test uses its JSDOM constructor alone.
import { JSDOM } from 'jsdom';
import { describe, expect, it } from 'vitest';

const VIEW = resolve(__dirname, '../../../../../lumen/ui/application/vnd.agience.transform+json/view.html');

type Sent = { jsonrpc: '2.0'; id?: number; method: string; params?: { name?: string; arguments?: Record<string, unknown> } };

const OP = 'op-answer';
const NOTE = 'note-1';
const CARD = {
  artifact_id: 'wf-1',
  context: { title: 'Notes', run: { type: 'workflow', steps: [
    { name: 'Answer', operator_id: OP, arguments: { question: 'what?', evidence: '@link.step1.evidence' } }] } },
};
// What Lumen reads: titles are sealed under their owners' keys, so they come back empty.
const CATALOG = {
  operators: [{ id: OP, group: 'mine', title: '', slug: 'answer' }],
  steps: [{ operator_id: OP, operator: '', links: { evidence: { id: NOTE, title: '' } } }],
  inbox_id: '',
};

function openView() {
  const sent: Sent[] = [];
  const html = readFileSync(VIEW, 'utf-8').replace('<script type="module">', '<script>');
  const dom = new JSDOM(html, {
    runScripts: 'dangerously',
    beforeParse(window: Window) {
      window.postMessage = ((msg: Sent) => { sent.push(msg); }) as typeof window.postMessage;
    },
  });
  const win = dom.window as Window & typeof globalThis;
  const deliver = (data: unknown) => win.dispatchEvent(new win.MessageEvent('message', { data }));
  const tick = () => new Promise((r) => setTimeout(r, 0));
  const answer = (name: string, result: unknown) => {
    const req = sent.find((m) => m.method === 'tools/call' && m.params?.name === name);
    if (!req) throw new Error(`the view did not ask for ${name}`);
    deliver({ jsonrpc: '2.0', id: req.id, result: { content: [{ type: 'text', text: JSON.stringify(result) }] } });
  };
  return { sent, deliver, tick, answer, doc: win.document };
}

const hidden = (doc: Document, id: string) => doc.getElementById(id)!.classList.contains('hidden');

describe('the workflow view', () => {
  it('shows its steps only once their operators and linked items are named', async () => {
    const { deliver, tick, answer, doc } = openView();
    deliver({ jsonrpc: '2.0', method: 'ui/notifications/tool-result',
      params: { content: [{ type: 'text', text: JSON.stringify(CARD) }] } });
    await tick();
    // Before the catalog is read: no half-named steps, no "no longer invoke".
    expect(hidden(doc, 'flowCard')).toBe(true);
    expect(hidden(doc, 'reading')).toBe(false);

    answer('workflow_catalog', CATALOG);
    await tick();
    expect(hidden(doc, 'flowCard')).toBe(true);
    answer('describe_operators', { operators: { [OP]: { title: 'Answer from my notes',
      input_schema: { type: 'object', properties: { question: { type: 'string' }, evidence: { type: 'string' } } } } } });
    await tick(); await tick();
    answer('describe_items', { items: { [NOTE]: { title: 'Smoke note' } } });
    await tick(); await tick();

    expect(hidden(doc, 'flowCard')).toBe(false);
    expect(hidden(doc, 'reading')).toBe(true);
    const steps = doc.getElementById('steps')!.textContent!;
    expect(steps).toContain('Answer from my notes');
    expect(steps).toContain('evidence: Smoke note');
    expect(steps).not.toContain('no longer invoke');
    const labels = [...(doc.getElementById('newOp') as HTMLSelectElement).options].map((o) => o.textContent);
    expect(labels).toEqual(['Choose an operator…', 'Answer from my notes']);
  });

  it('shows the steps with the reason when the catalog cannot be read', async () => {
    const { deliver, tick, sent, doc } = openView();
    deliver({ jsonrpc: '2.0', method: 'ui/notifications/tool-result',
      params: { content: [{ type: 'text', text: JSON.stringify(CARD) }] } });
    await tick();
    const req = sent.find((m) => m.params?.name === 'workflow_catalog')!;
    deliver({ jsonrpc: '2.0', id: req.id, error: { code: -32000, message: 'Mantle did not answer' } });
    await tick();
    expect(hidden(doc, 'flowCard')).toBe(false);
    expect(doc.getElementById('status')!.textContent).toBe('Mantle did not answer');
  });

  it('numbers its requests from its own starting point, so an earlier view\'s answer settles none', async () => {
    const one = openView(), two = openView();
    const first = (v: { sent: Sent[] }) => v.sent.find((m) => m.method === 'ui/initialize')!.id!;
    expect(first(one)).not.toBe(first(two));

    two.deliver({ jsonrpc: '2.0', method: 'ui/notifications/tool-result',
      params: { content: [{ type: 'text', text: JSON.stringify(CARD) }] } });
    await two.tick();
    const asked = two.sent.find((m) => m.params?.name === 'workflow_catalog')!.id!;
    // An answer numbered as the earlier view numbered it reaches this one and is dropped.
    const stale = first(one) + (asked - first(two));
    two.deliver({ jsonrpc: '2.0', id: stale, result: { content: [{ type: 'text', text: JSON.stringify({ operators: [], steps: [] }) }] } });
    await two.tick();
    expect(hidden(two.doc, 'flowCard')).toBe(true);
  });
});
