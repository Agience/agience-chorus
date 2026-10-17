/**
 * Product-level glossary entries intended for help pages/tooltips.
 *
 * This is structured data (not JSX) so it can drive multiple UIs:
 * - a Help/Glossary page
 * - tooltips
 * - onboarding
 */

export type GlossaryEntry = {
  id: string;
  term: string;
  aka?: string[];
  short?: string;
  body: string;
};

export const GLOSSARY_ENTRIES: GlossaryEntry[] = [
  {
    id: 'artifact',
    term: 'Artifact',
    aka: ['Card'],
    short: 'The basic object in Agience.',
    body: 'An Artifact is content plus its context: what it is, where it came from and who made it. It can hold text or media of any type, and it carries its own version history and provenance. On screen it shows as a card.',
  },
  {
    id: 'workspace',
    term: 'Workspace',
    short: 'The contents of a screen.',
    body: 'A Workspace is an artifact that holds the artifacts you are working with: an editable frame rather than a folder. Your Inbox is a Workspace.',
  },
  {
    id: 'collection',
    term: 'Collection',
    short: 'A subject that artifacts belong to.',
    body: 'A Collection groups artifacts by subject. Membership is many-to-many: adding an artifact to a collection links the same artifact rather than copying it, so one artifact can be in several collections and workspaces at once. Sharing a collection shares what is in it.',
  },
  {
    id: 'version',
    term: 'Version',
    short: 'Every edit is kept.',
    body: 'Editing an artifact writes a new version rather than overwriting the old one. The artifact you see is its newest version. Adding it to a collection or workspace is not an edit and makes no new version.',
  },
  {
    id: 'archived',
    term: 'Archived',
    short: 'Set aside, not deleted.',
    body: 'An archived artifact is left out of your workspaces, collections and search, and is read-only. Turn on the Archived filter in a workspace or collection to see its archived artifacts, and Restore one to bring it back.',
  },
  {
    id: 'trash',
    term: 'Trash',
    short: 'Deleted, and restorable for 30 days.',
    body: 'Delete moves an artifact to your Trash (the trash button at the top). It stays there for 30 days, where you can Restore it or delete it permanently; after that it is deleted for good.',
  },
  {
    id: 'source',
    term: 'Source',
    short: 'Where an artifact came from.',
    body: 'A Source is the transcript, file or artifact another artifact was derived from.',
  },
  {
    id: 'evidence',
    term: 'Evidence',
    short: 'Optional supporting detail.',
    body: 'Evidence links an artifact back to the passage of its source that supports it. It is optional and helps others trust what the artifact says.',
  },
  {
    id: 'metadata',
    term: 'Metadata',
    short: 'Tags and other context.',
    body: 'Metadata is the context attached to an artifact: tags, type, source and evidence. Search and filters use it.',
  },
];
