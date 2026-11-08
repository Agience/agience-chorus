// api/heldReach.ts
//
// Widenings of reach a peer sent, held by Mantle under threshold custody until a person here
// accepts them (`GET /held-reach`, `POST /held-reach/{id}/accept|reject`). Only the changes on
// resources the caller manages are listed. Accepting writes the change on the caller's own
// credential: Origin co-signs it or refuses, and a refused change stays held.

import { getList, post } from './api';

export interface HeldReachChange {
  id: number;
  kind: 'grant' | 'edge';
  resource_id: string;
  received_from: string | null;
  held_at: string | null;
  grantee_id?: string;
  grantee_type?: string;
  member_id?: string;
}

export function listHeldReach(): Promise<HeldReachChange[]> {
  return getList<HeldReachChange>('/held-reach');
}

export function acceptHeldReach(id: number): Promise<{ accepted: HeldReachChange }> {
  return post(`/held-reach/${id}/accept`, {});
}

export function rejectHeldReach(id: number): Promise<{ rejected: boolean }> {
  return post(`/held-reach/${id}/reject`, {});
}
