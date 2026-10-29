/**
 * api/agent.ts — server-tool invocation helpers.
 *
 * All tool invocations go through the canonical
 * ``POST /artifacts/{server_id}/op/invoke`` path on Crystal (the gateway). The
 * MCP server artifact's ``invoke`` operation (declared in
 * ``vnd.agience.mcp-server+json/type.json``) resolves ``body.name`` as the tool
 * to call on that server.
 *
 * Identity is always derived server-side from the auth token.
 */

import { post } from './api';

// ──────────────────────────────────────────────────────────────────────────────
// Information extraction
// ──────────────────────────────────────────────────────────────────────────────

export interface ExtractUnitsResponse {
  workspace_id: string;
  source_artifact_id: string;
  created_artifact_ids: string[];
  unit_count?: number;
  warning?: string;
}

/**
 * Extract structured information units from an artifact.
 *
 * Dispatches to Aria's ``extract_units`` tool. Creates new workspace
 * artifacts for each extracted unit; callers should refresh workspace
 * artifacts after this returns.
 */
export async function extractUnits(
  workspace_id: string,
  source_artifact_id: string,
  artifact_artifact_ids?: string[]
): Promise<ExtractUnitsResponse> {
  return post<ExtractUnitsResponse, unknown>(
    `/artifacts/aria/op/invoke`,
    {
      name: 'extract_units',
      workspace_id,
      arguments: {
        workspace_id,
        source_artifact_id,
        artifact_artifact_ids: artifact_artifact_ids ?? [],
      },
    },
  );
}

/** Alias for {@link extractUnits} — preferred name for content-type handlers. */
export const extractInformation = extractUnits;
