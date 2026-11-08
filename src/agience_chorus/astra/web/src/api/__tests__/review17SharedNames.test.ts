/**
 * Review 17: Facet digests an invite's target the way Origin and Mantle do (`prism.trust.ledger.
 * target_digest`). The vector is the one Origin's `test_the_invite_target_digest_is_one_function`
 * pins, so the three cannot drift apart.
 */
import { describe, expect, it } from 'vitest'

import { targetDigest } from '../authority'

describe('the invite target digest is one function across repos', () => {
  it('matches the shared vector', async () => {
    expect(await targetDigest('email', ' Bob@Team.Test ')).toBe(
      '119b27ebfd594700fbe4cf024fb3346e93a9153dbc55ef20ea0716a8da345da7')
  })
})
