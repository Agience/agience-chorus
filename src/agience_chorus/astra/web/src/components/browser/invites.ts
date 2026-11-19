import { getArtifact } from '@/api/artifacts';

/** How long, and how often, Accept waits for the new grant to reach the store before opening the
 *  shared item. A claim is made at Origin and the store reads Origin's ledger every few seconds,
 *  so the first read after Accept can still be refused (2026-11-13, the Tester). */
export const JOIN_WAIT_MS = 20000;
export const JOIN_POLL_MS = 1000;

/** Wait until the store lets this person read `resourceId`: true once it does, false if it has not
 *  within `waitMs`. Any refusal or error before then is taken as "not yet". */
export async function waitForAccess(resourceId: string, waitMs = JOIN_WAIT_MS, pollMs = JOIN_POLL_MS,
                                    read: (id: string) => Promise<unknown> = getArtifact,
                                    sleep = (ms: number) => new Promise((r) => setTimeout(r, ms)))
  : Promise<boolean> {
  const tries = Math.max(1, Math.ceil(waitMs / pollMs));
  for (let i = 0; i < tries; i += 1) {
    try {
      await read(resourceId);
      return true;
    } catch {
      if (i < tries - 1) await sleep(pollMs);
    }
  }
  return false;
}

/** Open a shared item by its address; a full load, so the workspace list includes it. */
export function openShared(resourceId: string): void {
  window.location.assign('/' + encodeURIComponent(resourceId));
}
