// context/workspace/issuedToken.tsx
//
// A type whose field issues a token (Mantle's `token` stamp: the Key) answers the create or the
// update that issues it once, under `issued`: `{field: raw token}`. The artifact keeps only the
// hash. The token is shown here, once, in the app's own dialog, and is stripped from the record
// before anything stores it, returns it to a caller, or posts it into a view.
import type { ConfirmContextValue } from '@/context/dialog/types';

export type Issued = Record<string, string>;

/** The record without `issued`, and the tokens it carried (null when it carried none). */
export function takeIssued<T extends object>(response: T): { record: T; issued: Issued | null } {
  if (!response || typeof response !== 'object' || !('issued' in response)) {
    return { record: response, issued: null };
  }
  const { issued, ...record } = response as T & { issued?: unknown };
  const tokens: Issued = {};
  if (issued && typeof issued === 'object') {
    for (const [field, raw] of Object.entries(issued as Record<string, unknown>)) {
      if (typeof raw === 'string' && raw) tokens[field] = raw;
    }
  }
  return { record: record as T, issued: Object.keys(tokens).length ? tokens : null };
}

/** Shows each issued token once. Resolves when the person closes the dialog. */
export async function showIssued(dialog: ConfirmContextValue | undefined, issued: Issued | null): Promise<void> {
  if (!issued || !dialog) return;
  for (const raw of Object.values(issued)) {
    await dialog.confirm({
      title: 'Copy your new key',
      description: 'It is shown once, here, and cannot be shown again. Archiving the Key ends it.',
      customContent: (
        <code
          data-testid="issued-token"
          className="block select-all break-all rounded bg-gray-50 p-2 text-xs"
        >
          {raw}
        </code>
      ),
      confirmLabel: 'Done',
      cancelLabel: 'Close',
      tone: 'warn',
    });
  }
}
