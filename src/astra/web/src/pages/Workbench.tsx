/**
 * pages/Workbench.tsx
 *
 * The converse facet of crystal.workbench (OPERATOR-ARCHITECTURE §12) — the human
 * conduit rendered. Left: converse with the lattice through the lumen tekton (wisdom &
 * inference). Right: the activated crystal itself — facets, tektons, organons, sha,
 * and the activation check — the ontology made visible.
 *
 * Signal flow (§12): the human's message enters the `web` facet (this page) → conducted
 * to the lumen tekton (its MCP endpoint, /lumen/mcp behind the crystal gateway) → the
 * tekton condenses → organons fire → the result exits the same facet.
 *
 * State handling: unauthenticated routes through the login flow (route is
 * LoginProtected); an unreachable tekton is reported as such; a tekton error surfaces
 * that message verbatim; an activation failure shows the failure reason as the finding.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowUp, Gem, ShieldAlert, ShieldCheck } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { proxyToolCall } from '@/api/mcp';
import { ActivationError, type ActivatedCrystal, activateWorkbench } from '@/crystal/activation';

// The lumen tekton's respond-shaped tool (agience-chorus/src/lumen/server.py):
// `synthesize(input, artifact_ids?, workspace_id?)` — question in, synthesis out.
const LUMEN_SERVER_REF = 'lumen';
const LUMEN_RESPOND_TOOL = 'synthesize';

interface ConverseMessage {
  role: 'human' | 'lumen' | 'refusal';
  text: string;
}

type TektonState = 'idle' | 'busy' | 'unreachable';

type ActivationState =
  | { status: 'checking' }
  | { status: 'activated'; activated: ActivatedCrystal }
  | { status: 'refused'; kind: string; reason: string; details: string[] };

function useWorkbenchActivation(): ActivationState {
  const [state, setState] = useState<ActivationState>({ status: 'checking' });
  useEffect(() => {
    let live = true;
    activateWorkbench()
      .then((activated) => {
        if (live) setState({ status: 'activated', activated });
      })
      .catch((e: unknown) => {
        if (!live) return;
        if (e instanceof ActivationError) {
          setState({ status: 'refused', kind: e.kind, reason: e.message, details: e.details });
        } else {
          setState({
            status: 'refused',
            kind: 'error',
            reason: e instanceof Error ? e.message : String(e),
            details: [],
          });
        }
      });
    return () => {
      live = false;
    };
  }, []);
  return state;
}

/** Turns an axios-shaped error into a plain description: no response means the tekton is unreachable. */
function describeTektonError(e: unknown): { unreachable: boolean; text: string } {
  const err = e as {
    response?: { status?: number; data?: unknown };
    code?: string;
    message?: string;
  };
  if (!err.response) {
    return {
      unreachable: true,
      text: 'lumen tekton unreachable — no response from the gateway' + (err.message ? ` (${err.message})` : ''),
    };
  }
  const status = err.response.status;
  if (status === 502 || status === 503 || status === 504) {
    return { unreachable: true, text: `lumen tekton unreachable — gateway answered ${status}` };
  }
  let detail = '';
  const data = err.response.data as { detail?: unknown } | string | undefined;
  if (typeof data === 'string') detail = data;
  else if (data && typeof data === 'object' && data.detail !== undefined) {
    detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail);
  }
  return {
    unreachable: false,
    text: `lumen refused (HTTP ${status})${detail ? `: ${detail}` : ''}`,
  };
}

// ---------------------------------------------------------------------------
// Converse (left) — the chat conduit to the lumen tekton
// ---------------------------------------------------------------------------

function ConversePanel() {
  const [messages, setMessages] = useState<ConverseMessage[]>([]);
  const [input, setInput] = useState('');
  const [tektonState, setTektonState] = useState<TektonState>('idle');
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || tektonState === 'busy') return;
    setInput('');
    setMessages((m) => [...m, { role: 'human', text }]);
    setTektonState('busy');
    try {
      const result = await proxyToolCall(LUMEN_RESPOND_TOOL, { input: text }, LUMEN_SERVER_REF);
      const reply = (result.content ?? [])
        .map((c) => c.text ?? '')
        .filter(Boolean)
        .join('\n');
      setMessages((m) => [
        ...m,
        reply
          ? { role: 'lumen', text: reply }
          : { role: 'refusal', text: 'lumen answered with no content — nothing to show' },
      ]);
      setTektonState('idle');
    } catch (e) {
      const { unreachable, text: errText } = describeTektonError(e);
      setMessages((m) => [...m, { role: 'refusal', text: errText }]);
      setTektonState(unreachable ? 'unreachable' : 'idle');
    }
  }, [input, tektonState]);

  return (
    <div className="flex flex-col h-full min-w-0">
      <div className="border-b px-4 py-2 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold">Converse</h2>
          <p className="text-xs text-muted-foreground">
            web facet → lumen tekton (/lumen/mcp · tool: {LUMEN_RESPOND_TOOL})
          </p>
        </div>
        {tektonState === 'unreachable' && (
          <span className="text-xs font-medium text-red-600 dark:text-red-400">tekton unreachable</span>
        )}
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {messages.length === 0 && (
          <p className="text-sm text-muted-foreground">
            Signal enters here. Your message flows through the web facet to the lumen tekton;
            what comes back is what the tekton actually condensed — errors and refusals are
            shown verbatim.
          </p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={m.role === 'human' ? 'flex justify-end' : 'flex justify-start'}>
            <div
              className={
                m.role === 'human'
                  ? 'max-w-[85%] rounded-lg bg-primary text-primary-foreground px-3 py-2 text-sm whitespace-pre-wrap'
                  : m.role === 'lumen'
                    ? 'max-w-[85%] rounded-lg bg-muted px-3 py-2 text-sm whitespace-pre-wrap'
                    : 'max-w-[85%] rounded-lg border border-red-300 dark:border-red-800 bg-red-50 dark:bg-red-950/40 text-red-800 dark:text-red-300 px-3 py-2 text-xs whitespace-pre-wrap'
              }
            >
              {m.text}
            </div>
          </div>
        ))}
        {tektonState === 'busy' && <p className="text-xs text-muted-foreground animate-pulse">lumen is condensing…</p>}
        <div ref={bottomRef} />
      </div>

      <div className="border-t p-3 flex gap-2">
        <textarea
          className="flex-1 resize-none rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          rows={2}
          placeholder="Ask the lattice…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              void send();
            }
          }}
        />
        <Button size="icon" onClick={() => void send()} disabled={!input.trim() || tektonState === 'busy'}>
          <ArrowUp className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Crystal panel (right) — the activated crystal, ontology visible
// ---------------------------------------------------------------------------

function CrystalPanel({ activation }: { activation: ActivationState }) {
  if (activation.status === 'checking') {
    return <p className="text-sm text-muted-foreground p-4">Activating crystal.workbench…</p>;
  }

  if (activation.status === 'refused') {
    return (
      <div className="p-4 space-y-2">
        <div className="flex items-center gap-2 text-red-700 dark:text-red-400">
          <ShieldAlert className="h-4 w-4" />
          <span className="text-sm font-semibold">Activation refused ({activation.kind})</span>
        </div>
        <p className="text-xs whitespace-pre-wrap">{activation.reason}</p>
        {activation.details.length > 0 && (
          <ul className="text-xs list-disc pl-5">
            {activation.details.map((d) => (
              <li key={d}>{d}</li>
            ))}
          </ul>
        )}
      </div>
    );
  }

  const { activated } = activation;
  const { crystal } = activated;
  const advertised = new Set(activated.prismCapabilities);

  return (
    <div className="p-4 space-y-4 overflow-y-auto text-sm">
      <div>
        <div className="flex items-center gap-2">
          <Gem className="h-4 w-4 text-primary" />
          <h2 className="font-semibold">{crystal.name}</h2>
        </div>
        <div className="mt-1 flex items-center gap-1.5 text-green-700 dark:text-green-400">
          <ShieldCheck className="h-3.5 w-3.5" />
          <span className="text-xs">activated — sha verified, capabilities subset-checked</span>
        </div>
        <p className="mt-1 text-[11px] font-mono break-all text-muted-foreground" title="sha256 (content address)">
          {activated.sha256}
        </p>
      </div>

      <section>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-1">
          Facets <span className="normal-case font-normal">— signal conduits</span>
        </h3>
        <ul className="space-y-0.5">
          {crystal.facets.map((f) => (
            <li key={f.name} className="flex items-baseline gap-2">
              <span className="font-mono text-xs">{f.name}</span>
              <span className="text-[11px] text-muted-foreground">
                {f.direction}
                {f.content_type ? ` · ${f.content_type} (hint)` : ''}
              </span>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-1">
          Tektons <span className="normal-case font-normal">— condensors</span>
        </h3>
        <ul className="space-y-0.5">
          {crystal.tektons.map((t) => (
            <li key={t.name} className="flex items-baseline gap-2">
              <span className="font-mono text-xs">{t.name}</span>
              <span className="text-[11px] text-muted-foreground">{t.domain}</span>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-1">
          Organons <span className="normal-case font-normal">— invoked instruments</span>
        </h3>
        <ul className="space-y-0.5">
          {activated.boundOrganons.map((o) => (
            <li key={o.name} className="flex items-baseline gap-2 flex-wrap">
              <span className="font-mono text-xs">{o.name}</span>
              <span className="text-[11px] text-muted-foreground">
                requires {(o.requires ?? []).join(', ') || '—'}
              </span>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-1">
          Prism junction <span className="normal-case font-normal">— one subset check</span>
        </h3>
        <p className="text-[11px] text-muted-foreground mb-1">
          Browser prism advertises; the crystal requires. Required ⊆ advertised → grounded.
        </p>
        <ul className="space-y-0.5">
          {activated.requiredCapabilities.map((c) => (
            <li key={c} className="flex items-center gap-1.5 text-xs">
              <ShieldCheck className="h-3 w-3 text-green-600 dark:text-green-400" />
              <span className="font-mono">{c}</span>
              <span className="text-[11px] text-muted-foreground">required · advertised</span>
            </li>
          ))}
          {activated.prismCapabilities
            .filter((c) => !activated.requiredCapabilities.includes(c))
            .map((c) => (
              <li key={c} className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <span className="inline-block h-3 w-3" />
                <span className="font-mono">{c}</span>
                <span className="text-[11px]">advertised</span>
              </li>
            ))}
        </ul>
        {/* Defensive display only — activation fails closed on any gap. */}
        {activated.requiredCapabilities.some((c) => !advertised.has(c)) && (
          <p className="text-xs text-red-600 mt-1">capability gap detected — this should have refused</p>
        )}
      </section>

      {crystal.lattice_seed?.collections && (
        <section>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-1">
            Lattice seed
          </h3>
          <p className="text-xs font-mono">{crystal.lattice_seed.collections.join(', ')}</p>
          <p className="text-[11px] text-muted-foreground">state grows from here; it never ships back</p>
        </section>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// The page
// ---------------------------------------------------------------------------

export default function Workbench() {
  const activation = useWorkbenchActivation();

  return (
    <div className="h-screen flex flex-col">
      <header className="border-b px-4 py-2 flex items-center gap-2">
        <Gem className="h-4 w-4 text-primary" />
        <h1 className="text-sm font-semibold">crystal.workbench</h1>
        <span className="text-xs text-muted-foreground">
          facets conduct · tektons condense · organons discharge (§12)
        </span>
      </header>
      <div className="flex-1 flex min-h-0">
        <div className="flex-1 min-w-0 border-r">
          <ConversePanel />
        </div>
        <aside className="w-96 shrink-0 overflow-y-auto bg-muted/20">
          <CrystalPanel activation={activation} />
        </aside>
      </div>
    </div>
  );
}
