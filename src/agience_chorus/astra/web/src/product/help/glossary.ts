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
    id: 'note',
    term: 'Note',
    aka: ['Artifact', 'Unit', 'Item'],
    short: 'The basic information object in Agience.',
    body: 'A Note is the basic information object in Agience. Notes can represent information and media of any type.',
  },
  {
    id: 'workspace',
    term: 'Workspace',
    short: 'A private space for your Notes.',
    body: 'A Workspace is a private area for creating, ingesting and curating Notes. Your Inbox is a Workspace.',
  },
  {
    id: 'collection',
    term: 'Collection',
    short: 'Durable, versioned truth.',
    body: 'A Collection is durable storage for Notes with version history. Searching across Collections is the default way to retrieve durable knowledge.',
  },
  {
    id: 'source',
    term: 'Source',
    short: 'Where a Note came from.',
    body: 'A Source is the transcript or artifact a Note is derived from.',
  },
  {
    id: 'evidence',
    term: 'Evidence',
    short: 'Optional supporting detail.',
    body: 'Evidence optionally supports a Note and links it back to the source transcript or artifact. It is encouraged and useful for trust, but not required for all workflows.',
  },
  {
    id: 'metadata',
    term: 'Metadata',
    short: 'Tags and fields power users rely on.',
    body: 'Metadata is structured context attached to Notes (tags, types, sources, evidence). It is often added and used by people “in the know” and can be leveraged for search, filtering, and future policy enforcement.',
  },
  {
    id: 'namespacing',
    term: 'Namespacing',
    short: 'Avoid collisions and enable privacy.',
    body: 'Today, Note context is a shared JSON bag. Over time we will likely reserve namespaced keys (e.g., agience.*, user.*, private.*) to avoid collisions and support privacy controls and redaction.',
  },
];
