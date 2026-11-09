// What the running app says it is: the platform release it was built for, and the agience-chorus
// commit it was built from. Both are read here, at build time, and nowhere else.
//
// `APP_RELEASE` is set by whatever builds a platform release (the publish workflow on a
// `release/<id>` branch, the release tool's own site build) and must be a release id, YYYY.MM.N;
// a build without one is `dev`. `package.json`'s `version` is not a displayed number.
import { execSync } from 'child_process'

export const RELEASE_ID = /^\d{4}\.\d{2}\.\d+$/

export interface BuildInfo {
  /** The platform release, or '' for a build that is not one. */
  release: string
  /** The short commit, or '' outside a git tree. */
  sha: string
}

export function buildInfo(env: Record<string, string | undefined>, gitSha: () => string = headSha): BuildInfo {
  const raw = (env.APP_RELEASE ?? '').trim()
  if (raw && !RELEASE_ID.test(raw)) {
    throw new Error(`APP_RELEASE=${JSON.stringify(raw)} is not a platform release id (YYYY.MM.N)`)
  }
  return { release: raw, sha: (env.GIT_SHA ?? '').trim() || gitSha() }
}

function headSha(): string {
  try {
    return execSync('git rev-parse --short HEAD', { stdio: ['ignore', 'pipe', 'ignore'] }).toString().trim()
  } catch {
    return '' // not a git tree
  }
}
