import { PaletteState } from '../palette.types';

export async function contextHandler(state: PaletteState): Promise<PaletteState> {
  // Context panel data is already in state.panelData.context
  // Handler does nothing - the panel data is the context
  return state;
}
