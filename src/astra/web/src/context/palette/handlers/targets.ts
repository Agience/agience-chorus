import { PaletteState } from '../palette.types';

export async function targetsHandler(state: PaletteState): Promise<PaletteState> {
  // Passthrough: panelData.targets already holds the targets data, so there is nothing to transform.
  return state;
}
