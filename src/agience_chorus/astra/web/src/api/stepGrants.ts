// api/stepGrants.ts
//
// Whichever artifact holds a step holds that step's grants (FR-007). A workflow with inline steps
// is itself the holder: it holds Invoke on each operator a step invokes and Read on each item a
// step links. The person makes those grants in their own Origin session when they save the
// workflow, through their Update on it; Origin's ledger decides each one. A run's token reaches
// what the workflow holds and nothing else.

import { listGrantsAtOrigin, makeGrant } from './authority';

const LINK = '@link.';

interface Step { operator_id?: unknown; arguments?: unknown }

/** What a workflow's inline steps need it to hold: each item and the one action on it. */
export function stepNeeds(run: unknown, links: Record<string, string>): Array<[string, string]> {
  const steps = ((run ?? {}) as { type?: unknown; steps?: unknown })
  if (steps.type !== 'workflow' || !Array.isArray(steps.steps)) return []
  const out = new Map<string, string>()
  for (const step of steps.steps as Step[]) {
    const op = typeof step?.operator_id === 'string' ? step.operator_id : ''
    if (op) out.set(op, 'invoke')
    for (const value of Object.values((step?.arguments ?? {}) as Record<string, unknown>)) {
      if (typeof value !== 'string' || !value.startsWith(LINK)) continue
      const target = links[value.slice(LINK.length)]
      if (target && !out.has(target)) out.set(target, 'read')
    }
  }
  return [...out.entries()]
}

/** The grants the workflow lacks for its steps, made now. Returns the items Origin refused. */
export async function holdStepGrants(workflowId: string, run: unknown,
                                     links: Record<string, string>): Promise<string[]> {
  const refused: string[] = []
  for (const [resourceId, action] of stepNeeds(run, links)) {
    if (resourceId === workflowId) continue
    const held = await listGrantsAtOrigin(resourceId).catch(() => [])
    if (held.some((g) => {
      const row = g as unknown as Record<string, unknown>
      return g.grantee_type === 'artifact' && g.grantee_id === workflowId && g.state === 'active'
        && row.effect !== 'deny' && Boolean(row[`can_${action}`])
    })) continue
    try {
      await makeGrant(resourceId, { grantee_type: 'artifact', grantee_id: workflowId,
                                    actions: [action] })
    } catch {
      refused.push(resourceId)
    }
  }
  return refused
}
