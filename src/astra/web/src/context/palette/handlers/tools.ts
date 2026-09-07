import { PaletteState } from '../palette.types';

export async function toolsHandler(state: PaletteState, user_id: string): Promise<PaletteState> {
  void user_id;
  // Tools panel is configuration only: the selected tools already live in
  // state.panelData.tools, so this handler is a passthrough that generates
  // no synthetic knowledge artifacts.
  return state;
}
