import { describe, expect, it } from 'vitest'
import { buildInfo } from './build-info'

describe('buildInfo', () => {
  it('a build with the release set is exactly that release', () => {
    expect(buildInfo({ APP_RELEASE: '2026.11.4', GIT_SHA: '6da03e5' }, () => 'unused'))
      .toEqual({ release: '2026.11.4', sha: '6da03e5' })
  })

  it('a daily release id, YYYYMM.DD.N, is a release too', () => {
    expect(buildInfo({ APP_RELEASE: '202611.12.1', GIT_SHA: 'a' }, () => '').release).toBe('202611.12.1')
    expect(() => buildInfo({ APP_RELEASE: '202611.12' }, () => '')).toThrow()
  })

  it('a build with no release is not one, and takes the tree\'s commit', () => {
    expect(buildInfo({}, () => 'abc1234')).toEqual({ release: '', sha: 'abc1234' })
    expect(buildInfo({ APP_RELEASE: '' }, () => 'abc1234').release).toBe('')
  })

  it('a value that is not a release id stops the build', () => {
    expect(() => buildInfo({ APP_RELEASE: '0.3.2' }, () => '')).toThrow(/not a platform release id/)
    expect(() => buildInfo({ APP_RELEASE: 'release/2026.11.4' }, () => '')).toThrow()
  })
})
