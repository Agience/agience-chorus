// Renders nothing: stream and inbound keys are managed per source artifact
// (vnd.agience.stream+json, vnd.agience.telegram+json, etc.), and the key
// generate/rotate UX lives in each artifact's viewer.
export default function WorkspaceInboundKeysModal() {
  return null;
}
