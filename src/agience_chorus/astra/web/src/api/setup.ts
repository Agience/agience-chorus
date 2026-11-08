/**
 * api/setup.ts
 *
 * Setup wizard and operator settings API client.
 */

import { get, post } from './api'

// ---------------------------------------------------------------------------
//  Setup wizard (unauthenticated, only available during setup mode)
// ---------------------------------------------------------------------------

export type SetupStatus = {
  needs_setup: boolean
  ready: boolean
  version: string
  env_defaults?: Record<string, boolean | string>
}

export type ValidateConnectionResult = {
  success: boolean
  error: string | null
}

export type OperatorAccount = {
  email?: string
  password?: string
  name?: string
  passkey_credential?: Record<string, unknown>
  passkey_challenge?: string
  passkey_device_name?: string
}

export type SettingInput = {
  key: string
  value: string
  category: string
  is_secret?: boolean
}

export type SetupCompleteResult = {
  access_token: string
  refresh_token: string
  token_type: string
}

export async function getSetupStatus(): Promise<SetupStatus> {
  return get<SetupStatus>('/setup/status')
}

export async function validateSetupToken(token: string): Promise<boolean> {
  const res = await post<{ valid: boolean }>('/setup/validate-token', { token })
  return res.valid
}

export async function validateConnection(
  setupToken: string,
  service: string,
  config: Record<string, unknown>
): Promise<ValidateConnectionResult> {
  return post<ValidateConnectionResult>(
    '/setup/validate-connection',
    { service, config },
    { headers: { 'X-Setup-Token': setupToken } }
  )
}

export async function completeSetup(
  setupToken: string,
  operator: OperatorAccount | null,
  settings: SettingInput[]
): Promise<SetupCompleteResult> {
  return post<SetupCompleteResult>(
    '/setup/complete',
    { operator, settings },
    { headers: { 'X-Setup-Token': setupToken } }
  )
}

// Signing in (a password, a mailed code, a passkey, a new account) happens only on Origin's own
// pages, never in this app (`pages/Login.tsx`, `auth/originSignIn.ts`).

// Platform settings API lives in `api/platform.ts`. Use
// `getPlatformSettings` / `updatePlatformSettings` from there.
