/**
 * A timer's job grant, approved or stopped at Origin's own page (John, 2026-11-10).
 *
 * A timer runs on a job grant the person makes at Origin, in their Origin session with a step-up:
 * job `lumen.timer.<timer id>`, over their own key, reaching only what the timer runs. The app
 * opens Origin's `/job-grant` page in a window of its own, and the page posts back the grant's id,
 * to this app's origin alone, once the person approves it there. Nothing here makes a grant: the
 * app only asks, and listens for Origin's answer from that window.
 */
import { getRuntimeConfig } from '../config/runtime';

export const TIMER_JOB_PREFIX = 'lumen.timer.';

/** How long the app waits for the person to answer at Origin's page. */
const ANSWER_MS = 10 * 60 * 1000;

function originBase(): URL {
  return new URL(getRuntimeConfig().originUri || '/', window.location.href);
}

export class JobGrantRefused extends Error {}

/** Open Origin's page and resolve with the first answer `accept` takes from it. */
function askOrigin<T>(params: Record<string, string>, accept: (data: Record<string, unknown>) => T | undefined): Promise<T> {
  const base = originBase();
  const url = new URL('/job-grant', base);
  url.search = new URLSearchParams({ ...params, back: window.location.origin }).toString();
  const popup = window.open(url.toString(), 'agience-job-grant', 'popup,width=520,height=720');
  if (!popup) {
    return Promise.reject(new JobGrantRefused('The browser blocked Origin\'s window; allow pop-ups for this site and try again.'));
  }
  return new Promise<T>((resolve, reject) => {
    let settled = false;
    const finish = (fn: () => void) => {
      if (settled) return;
      settled = true;
      window.removeEventListener('message', onMessage);
      window.clearInterval(watch);
      window.clearTimeout(timeout);
      fn();
    };
    const onMessage = (event: MessageEvent) => {
      if (event.origin !== base.origin || event.source !== popup) return;
      const data = (event.data ?? {}) as Record<string, unknown>;
      if (typeof data.type === 'string' && data.type.endsWith('-declined')) {
        finish(() => reject(new JobGrantRefused('You did not approve it at Origin.')));
        return;
      }
      const got = accept(data);
      if (got !== undefined) finish(() => resolve(got));
    };
    window.addEventListener('message', onMessage);
    const watch = window.setInterval(() => {
      if (popup.closed) finish(() => reject(new JobGrantRefused('Origin\'s window closed before it was approved.')));
    }, 500);
    const timeout = window.setTimeout(
      () => finish(() => reject(new JobGrantRefused('No answer from Origin\'s window.'))), ANSWER_MS);
  });
}

/** The id of the job grant the person approves at Origin for this timer. */
export function approveTimerAtOrigin(timerId: string, reach: string[], title: string, days = 30): Promise<string> {
  const job = `${TIMER_JOB_PREFIX}${timerId}`;
  return askOrigin(
    { job, reach: reach.join(','), title, days: String(days) },
    (data) => (data.type === 'agience.job-grant' && data.job === job && typeof data.grant_id === 'string'
      && data.grant_id ? data.grant_id : undefined),
  );
}

export const RUN_JOB_PREFIX = 'lumen.run.';

/** A workflow's one run, now (John, 2026-11-10): the job name and the id of the one-shot grant the
 *  person approves at Origin for it. Origin bounds it to minutes and a single run. */
export async function approveRunAtOrigin(workflowId: string, reach: string[], title: string): Promise<{ job: string; grantId: string }> {
  const nonce = Array.from(crypto.getRandomValues(new Uint8Array(6)), (b) => b.toString(16).padStart(2, '0')).join('');
  const job = `${RUN_JOB_PREFIX}${workflowId}.${nonce}`;
  const grantId = await askOrigin(
    { job, reach: reach.join(','), title },
    (data) => (data.type === 'agience.job-grant' && data.job === job && typeof data.grant_id === 'string'
      && data.grant_id ? data.grant_id : undefined),
  );
  return { job, grantId };
}

/** Resolves once the person stops the grant at Origin. */
export function revokeAtOrigin(grantId: string, title: string): Promise<void> {
  return askOrigin(
    { revoke: grantId, title },
    (data) => (data.type === 'agience.job-grant-revoked' && data.grant_id === grantId ? true : undefined),
  ).then(() => undefined);
}
