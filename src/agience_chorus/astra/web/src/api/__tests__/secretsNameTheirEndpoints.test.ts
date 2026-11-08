/**
 * Review 11: a credential names where its secret may go (`allowed_endpoints`), and that list is
 * sealed with the secret when the credential is written. An older credential names none, so its
 * Admin rewrites it: writes it again with its endpoints, then removes the old one.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'

import api from '../api'
import { addSecret, rewriteSecret } from '../secrets'

afterEach(() => vi.restoreAllMocks())

describe('a credential and its endpoints', () => {
  it('is written with the endpoints it names', async () => {
    const posted: unknown[] = []
    vi.spyOn(api, 'post').mockImplementation(async (_url: string, body?: unknown) => {
      posted.push(body)
      return { data: { id: 'c-1' } } as never
    })
    vi.spyOn(api, 'get').mockResolvedValue({ data: { items: [], has_more: false } } as never)
    await addSecret({ type: 'llm_key', provider: 'openai', label: 'k', value: 'v',
                      allowed_endpoints: ['https://api.openai.com/v1'] })
    const ctx = JSON.parse((posted[0] as { context: string }).context)
    expect(ctx.allowed_endpoints).toEqual(['https://api.openai.com/v1'])
  })

  it('refuses an endpoint that is not an https URL before anything is written', async () => {
    const post = vi.spyOn(api, 'post')
    await expect(addSecret({ type: 'llm_key', provider: 'x', label: 'k', value: 'v',
                             allowed_endpoints: ['http://plain.test/'] })).rejects.toThrow()
    expect(post).not.toHaveBeenCalled()
  })

  it('rewrites an older credential: written again with endpoints, then the old one removed', async () => {
    const calls: string[] = []
    vi.spyOn(api, 'post').mockImplementation(async (url: string) => {
      calls.push(`post ${url}`)
      return { data: { id: 'c-2' } } as never
    })
    vi.spyOn(api, 'delete').mockImplementation(async (url: string) => {
      calls.push(`delete ${url}`)
      return { data: {} } as never
    })
    vi.spyOn(api, 'get').mockResolvedValue({ data: { items: [], has_more: false } } as never)
    await rewriteSecret('c-1', { type: 'llm_key', provider: 'openai', label: 'k', value: 'v',
                                 allowed_endpoints: ['https://api.openai.com/v1'] })
    expect(calls).toEqual(['post /artifacts', 'delete /artifacts/c-1'])
  })
})
