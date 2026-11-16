import { describe, expect, it } from 'vitest'
import { unresolvedCssUrls } from '../css-urls'

const emitted = new Set(['assets/dm-sans-latin-opsz-normal-AbC123.woff2', 'assets/index-x.css'])

describe('unresolvedCssUrls', () => {
  it('passes a url() naming an emitted file, quoted or not', () => {
    expect(unresolvedCssUrls("src:url(/assets/dm-sans-latin-opsz-normal-AbC123.woff2) format('woff2')", emitted)).toEqual([])
    expect(unresolvedCssUrls('src:url("/assets/dm-sans-latin-opsz-normal-AbC123.woff2?v=1")', emitted)).toEqual([])
  })

  it('passes inline data and fragments', () => {
    expect(unresolvedCssUrls('a{b:url(data:image/svg+xml;base64,AAAA)} c{d:url(#m)}', emitted)).toEqual([])
  })

  it('refuses the bare package path Vite copies through unresolved', () => {
    const css = "src:url(@fontsource-variable/dm-sans/files/dm-sans-latin-opsz-normal.woff2) format('woff2-variations')"
    expect(unresolvedCssUrls(css, emitted)).toEqual(['@fontsource-variable/dm-sans/files/dm-sans-latin-opsz-normal.woff2'])
  })

  it('refuses an asset path the build did not emit', () => {
    expect(unresolvedCssUrls('a{b:url(/assets/missing.woff2)}', emitted)).toEqual(['/assets/missing.woff2'])
  })
})
