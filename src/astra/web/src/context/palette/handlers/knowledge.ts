import { PaletteState } from '../palette.types';

export async function knowledgeHandler(state: PaletteState): Promise<PaletteState> {
  // Passthrough: panelData.knowledge already holds the knowledge data, so there is nothing to transform.
  return state;
}
