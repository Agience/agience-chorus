import { PaletteState } from '../palette.types';

export async function optionsHandler(state: PaletteState): Promise<PaletteState> {
  // Passthrough: panelData.options already holds the options data, so there is nothing to transform.
  return state;
}
