import { PaletteState } from '../palette.types';

export async function inputHandler(state: PaletteState): Promise<PaletteState> {
  // Passthrough: panelData.input already holds the input data, so there is nothing to transform.
  return state;
}
