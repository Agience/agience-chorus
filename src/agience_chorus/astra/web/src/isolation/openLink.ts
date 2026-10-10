/**
 * The link schemes a sandboxed view may ask the host to open with `ui/open-link`.
 *
 * Only absolute http: and https: URLs. A `javascript:` URL opened by the host would run in a
 * window the view does not own; `data:`, `blob:` and `file:` would let the view put content of its
 * choosing in a top-level tab.
 */
export function isWebUrl(url: string): boolean {
  try {
    const { protocol } = new URL(url);
    return protocol === 'http:' || protocol === 'https:';
  } catch {
    return false;
  }
}
