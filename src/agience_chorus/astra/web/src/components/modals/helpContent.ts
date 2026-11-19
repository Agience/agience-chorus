/** Where "Send feedback" writes to: the address the app's privacy and cookie pages name. */
export const FEEDBACK_HREF = 'mailto:connect@agience.ai?subject=Agience%20feedback';

/** The five things a new person does first, in order. */
export const GET_STARTED_STEPS: Array<{ title: string; body: string }> = [
  { title: 'Open a workspace', body: 'A workspace holds your work. Pick one from the sidebar, or make a new one with New workspace.' },
  { title: 'Add an artifact', body: 'New artifact adds a note, a file or any other kind of item to the workspace you are in.' },
  { title: 'Group artifacts in a collection', body: 'A collection gathers related artifacts. Drag artifacts into it, or add them from the artifact menu.' },
  { title: 'Build a workflow', body: 'A workflow runs steps for you. Add a step, choose what it does, and Run now; arm a timer to run it on a schedule.' },
  { title: 'Share it', body: 'Share a workspace or collection with someone, and choose what they may do: read, add or edit.' },
];

/** "a" or "an" for the word that follows. */
export function article(word: string): string {
  return /^[aeiou]/i.test(word) ? 'an' : 'a';
}
