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

// ---------------------------------------------------------------------------
//  Passkey auth
// ---------------------------------------------------------------------------

export type PasskeyLoginOptions = {
  options: Record<string, unknown> | null
  has_passkeys: boolean
}

export async function getPasskeyLoginOptions(email: string): Promise<PasskeyLoginOptions> {
  return post<PasskeyLoginOptions>('/auth/passkey/login-options', { email })
}

/**
 * `challenge` is echoed back purely as a lookup key for the challenge the server
 * issued and recorded; the server derives both the expected challenge and the
 * user from its own stored row. The client never names which account it is
 * authenticating as.
 */
export async function completePasskeyLogin(
  credential: Record<string, unknown>,
  challenge: string
): Promise<{ access_token: string; refresh_token: string }> {
  return post('/auth/passkey/login-complete', {
    credential,
    challenge,
  })
}

export async function getPasskeyRegisterOptions(): Promise<{ options: Record<string, unknown> }> {
  return post('/auth/passkey/register-options', {})
}

export async function completePasskeyRegistration(
  credential: Record<string, unknown>,
  challenge: string,
  deviceName?: string
): Promise<{ credential_id: string }> {
  return post('/auth/passkey/register-complete', {
    credential,
    challenge,
    device_name: deviceName,
  })
}

// ---------------------------------------------------------------------------
//  OTP auth
// ---------------------------------------------------------------------------

export async function requestOTP(email: string): Promise<{ sent: boolean }> {
  return post('/auth/otp/request', { email })
}

export async function verifyOTP(
  email: string,
  code: string
): Promise<{ access_token: string; refresh_token: string }> {
  return post('/auth/otp/verify', { email, code })
}

// Platform settings API lives in `api/platform.ts`. Use
// `getPlatformSettings` / `updatePlatformSettings` from there.
