// Every url() in the built CSS names a file the build emitted (or is inline data). A url() Vite
// could not resolve is copied through unchanged; the browser then asks the server for a path that
// does not exist, the app's fallback answers with index.html, and the font or image silently
// fails. The build refuses that instead of shipping it.
import type { Plugin } from 'vite'

const URL_RE = /url\(\s*(['"]?)([^'")]+)\1\s*\)/g

/** The url() targets in `css` that are not inline data, a fragment, or a file in `emitted`. */
export function unresolvedCssUrls(css: string, emitted: Set<string>, base = '/'): string[] {
  const bad: string[] = []
  for (const m of css.matchAll(URL_RE)) {
    const target = m[2].trim()
    if (target.startsWith('data:') || target.startsWith('#')) continue
    const path = target.split(/[?#]/)[0]
    const rel = path.startsWith(base) ? path.slice(base.length) : path.replace(/^\.\//, '')
    if (!emitted.has(rel)) bad.push(target)
  }
  return bad
}

export function cssUrlsResolved(base = '/'): Plugin {
  return {
    name: 'agience-css-urls-resolved',
    apply: 'build',
    enforce: 'post',
    generateBundle(_options, bundle) {
      const emitted = new Set(Object.keys(bundle))
      const bad: string[] = []
      for (const [name, out] of Object.entries(bundle)) {
        if (out.type !== 'asset' || !name.endsWith('.css')) continue
        const css = typeof out.source === 'string' ? out.source : new TextDecoder().decode(out.source)
        for (const u of unresolvedCssUrls(css, emitted, base)) bad.push(`${name}: url(${u})`)
      }
      if (bad.length) {
        this.error(`the built CSS names files the build did not emit:\n  ${bad.join('\n  ')}`)
      }
    },
  }
}
