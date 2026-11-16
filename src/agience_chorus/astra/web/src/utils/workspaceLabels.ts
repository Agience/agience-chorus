// utils/workspaceLabels.ts
//
// The label each workspace is listed by (BUG-001): its name, and, where another workspace in the
// same list has that name, the day it was made, so the two can be told apart in the tabs, the Dock
// picker, the sidebar and the command palette. Two made the same day also show the time; the same
// minute, the seconds; the same second, a number in the order they were made, so no two listed
// workspaces ever share a label (2026-11-15, the Tester: two made in one minute did).

type Listed = { id: string; name?: string; created_time?: string };

export const UNTITLED_WORKSPACE = 'Untitled workspace';

function shownName(ws: Listed): string {
  return String(ws.name ?? '').trim() || UNTITLED_WORKSPACE;
}

function day(when: Date, now: Date): string {
  return when.toLocaleDateString('en-CA', {
    month: 'short',
    day: 'numeric',
    ...(when.getFullYear() === now.getFullYear() ? {} : { year: 'numeric' }),
  });
}

function time(when: Date, seconds = false): string {
  return when.toLocaleTimeString('en-CA', { hour: '2-digit', minute: '2-digit', ...(seconds ? { second: '2-digit' } : {}) });
}

/** `{workspace id: label}` for every workspace in `workspaces`. */
export function workspaceLabels(workspaces: readonly Listed[], now: Date = new Date()): Map<string, string> {
  const byName = new Map<string, Listed[]>();
  for (const ws of workspaces) {
    const key = shownName(ws).toLocaleLowerCase();
    byName.set(key, [...(byName.get(key) ?? []), ws]);
  }
  const labels = new Map<string, string>();
  for (const group of byName.values()) {
    if (group.length === 1) {
      labels.set(String(group[0].id), shownName(group[0]));
      continue;
    }
    const dated = group.map((ws) => {
      const when = ws.created_time ? new Date(ws.created_time) : null;
      return { ws, when: when && !Number.isNaN(when.getTime()) ? when : null };
    });
    const count = (keys: string[]) => keys.reduce((m, k) => m.set(k, (m.get(k) ?? 0) + 1), new Map<string, number>());
    const days = count(dated.filter((d) => d.when).map((d) => day(d.when!, now)));
    const minutes = count(dated.filter((d) => d.when).map((d) => `${day(d.when!, now)} ${time(d.when!)}`));
    const shown = dated.map(({ ws, when }) => {
      if (!when) return { ws, when, label: shownName(ws) };
      const d = day(when, now);
      const m = `${d} ${time(when)}`;
      const at = (days.get(d) ?? 0) < 2 ? d : (minutes.get(m) ?? 0) < 2 ? m : `${d} ${time(when, true)}`;
      return { ws, when, label: `${shownName(ws)} · ${at}` };
    });
    // Still the same (the same second, or no time at all): numbered in the order they were made.
    const left = count(shown.map((x) => x.label));
    const seen = new Map<string, number>();
    const ordered = [...shown].sort((a, b) => (a.when?.getTime() ?? 0) - (b.when?.getTime() ?? 0)
      || String(a.ws.id).localeCompare(String(b.ws.id)));
    for (const x of ordered) {
      if ((left.get(x.label) ?? 0) < 2) { labels.set(String(x.ws.id), x.label); continue; }
      const n = (seen.get(x.label) ?? 0) + 1;
      seen.set(x.label, n);
      labels.set(String(x.ws.id), n === 1 ? x.label : `${x.label} (${n})`);
    }
  }
  return labels;
}

/** The label of one workspace among `workspaces`. */
export function workspaceLabel(ws: Listed, workspaces: readonly Listed[], now?: Date): string {
  return workspaceLabels(workspaces, now).get(String(ws.id)) ?? shownName(ws);
}
