// utils/workspaceLabels.ts
//
// The label each workspace is listed by: its name, and, where another workspace the caller can
// reach has that name, as much of the time it was made as tells them apart, so the two differ in
// the tabs, the Dock picker, the sidebar and the command palette. Crystal decides which workspaces
// share a name and how much of the time each needs (`label_at`), and numbers those that still
// match (`label_n`); this only writes the label out.

import type { Workspace } from '@/api/types/workspace';
import { formatClock, formatDay } from './dates';

export type Listed = Pick<Workspace, 'id'> & Partial<Pick<Workspace, 'name' | 'created_time' | 'label_at' | 'label_n'>>;

function shownName(ws: Listed): string {
  return String(ws.name ?? '').trim();
}

function shownTime(ws: Listed, now: Date): string {
  const when = ws.label_at && ws.created_time ? new Date(ws.created_time) : null;
  if (!when || Number.isNaN(when.getTime())) return '';
  const day = formatDay(when, now);
  if (ws.label_at === 'day') return ` · ${day}`;
  return ` · ${day} ${formatClock(when, ws.label_at === 'second')}`;
}

/** The label of one workspace, from the marks Mantle listed it with. */
export function workspaceLabel(ws: Listed, now: Date = new Date()): string {
  const n = ws.label_n && ws.label_n > 1 ? ` (${ws.label_n})` : '';
  return `${shownName(ws)}${shownTime(ws, now)}${n}`;
}

/** `{workspace id: label}` for every workspace in `workspaces`. */
export function workspaceLabels(workspaces: readonly Listed[], now: Date = new Date()): Map<string, string> {
  return new Map(workspaces.map((ws) => [String(ws.id), workspaceLabel(ws, now)]));
}
