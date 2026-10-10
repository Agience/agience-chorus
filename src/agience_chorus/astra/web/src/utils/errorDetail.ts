// utils/errorDetail.ts

/**
 * The server's reason for a failed request, for showing to the user.
 *
 * Reads `response.data.detail` from an axios error. FastAPI sends it as a string for an
 * HTTPException, as a list of `{ msg }` for a validation error, and as an object for a few
 * structured refusals; each is reduced to one line. Anything else yields `fallback`.
 */
export function errorDetail(err: unknown, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((d) => (d && typeof d === 'object' && typeof (d as { msg?: unknown }).msg === 'string' ? (d as { msg: string }).msg : null))
      .filter((m): m is string => Boolean(m));
    if (msgs.length) return msgs.join('; ');
  }
  if (detail && typeof detail === 'object') {
    const message = (detail as { message?: unknown }).message;
    if (typeof message === 'string' && message.trim()) return message;
  }
  return fallback;
}
