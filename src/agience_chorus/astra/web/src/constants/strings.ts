/**
 * Centralized UI strings for consistency across the application.
 * Organized by feature area for easier maintenance.
 */

import { PRODUCT_NOUN, noun } from '@/product/copy';

/** Days an artifact stays in Trash before it is deleted for good (Mantle's `trash.RETENTION_DAYS`). */
export const TRASH_RETENTION_DAYS = 30;

/** The window event that opens Trash from anywhere in the app. */
export const OPEN_TRASH_EVENT = 'agience:open-trash';

// Artifact deletion/removal confirmations
export const CARD_CONFIRM = {
  DELETE_TITLE: `Move this ${PRODUCT_NOUN.singular.toLowerCase()} to Trash?`,
  DELETE_DESCRIPTION: `You can restore it from Trash for ${TRASH_RETENTION_DAYS} days. After that it is deleted for good.`,
  DELETE_CONFIRM: 'Move to Trash',
  DELETE_PERMANENT_TITLE: `Delete ${PRODUCT_NOUN.singular.toLowerCase()} permanently?`,
  DELETE_PERMANENT_DESCRIPTION: `Deleting this ${PRODUCT_NOUN.singular.toLowerCase()} permanently removes it and all its content. This cannot be undone.`,
  DELETE_PERMANENT_CONFIRM: 'Delete permanently',
  ARCHIVE_TITLE: `Archive this ${PRODUCT_NOUN.singular.toLowerCase()}?`,
  ARCHIVE_DESCRIPTION: `This will hide the ${PRODUCT_NOUN.singular.toLowerCase()} from active views until restored.`,
  ARCHIVE_CONFIRM: 'Archive',
} as const;

// Bulk operations confirmations
export const BULK_CONFIRM = {
  DELETE_TITLE: (count: number) => `Move ${count} ${noun(count).toLowerCase()} to Trash?`,
  DELETE_DESCRIPTION: (count: number) => `You can restore ${count === 1 ? 'it' : 'them'} from Trash for ${TRASH_RETENTION_DAYS} days. After that ${count === 1 ? 'it is' : 'they are'} deleted for good.`,
  DELETE_CONFIRM: 'Move to Trash',
  ARCHIVE_TITLE: (count: number) => `Archive ${count} ${noun(count).toLowerCase()}?`,
  ARCHIVE_DESCRIPTION: (count: number) => `${count === 1 ? `This ${PRODUCT_NOUN.singular.toLowerCase()}` : `These ${PRODUCT_NOUN.plural.toLowerCase()}`} ${count === 1 ? 'will' : 'will'} be moved to archived state and can be restored later.`,
} as const;

// API key/share deletion confirmations
export const API_KEY_CONFIRM = {
  DELETE_TITLE: (name: string) => `Delete API key "${name}"?`,
  DELETE_DESCRIPTION: 'This will immediately revoke access for any systems using this key. They will need to re-authenticate with a new key.',
  DELETE_CONFIRM: 'Delete key',
} as const;

// Workspace inbound key confirmations
export const INBOUND_KEY_CONFIRM = {
  DELETE_TITLE: 'Delete inbound key?',
  DELETE_DESCRIPTION: 'This will revoke access for any external systems using this key. This action cannot be undone.',
  DELETE_CONFIRM: 'Delete key',
} as const;

// Workspace streaming key confirmations
export const STREAM_KEY_CONFIRM = {
  ROTATE_TITLE: 'Generate/rotate streaming key?',
  ROTATE_DESCRIPTION: 'This will invalidate the previous streaming key for this workspace. Update any OBS profiles (and transcription gateways) that use it.',
  ROTATE_CONFIRM: 'Rotate key',
} as const;

// Collection status labels
export const COLLECTION_STATUS = {
  READ_ONLY: 'read-only',
  ARCHIVED: 'archived',
  BLOCKED: 'blocked',
} as const;

// Artifact state labels
export const CARD_STATE = {
  LIVE: 'live',
  ARCHIVED: 'archived',
} as const;

// Keyboard shortcut descriptions
export const SHORTCUTS = {
  SELECT_ALL: {
    LABEL: `Select all ${PRODUCT_NOUN.plural.toLowerCase()}`,
    DESCRIPTION: `Select all visible ${PRODUCT_NOUN.plural.toLowerCase()} in the current workspace`,
  },
  CLEAR_SELECTION: {
    LABEL: 'Clear selection',
    DESCRIPTION: `Clear all selected ${PRODUCT_NOUN.plural.toLowerCase()}`,
  },
  OPEN_SHORTCUTS: {
    LABEL: 'Show keyboard shortcuts',
    DESCRIPTION: 'View all available keyboard shortcuts',
  },
  OPEN_COMMAND_PALETTE: {
    LABEL: 'Open command palette',
    DESCRIPTION: 'Quick access to commands and navigation',
  },
  FOCUS_SEARCH: {
    LABEL: 'Focus global search',
    DESCRIPTION: 'Jump to the search input',
  },
} as const;

// Common button labels
export const BUTTON_LABELS = {
  CANCEL: 'Cancel',
  CLOSE: 'Close',
  DELETE: 'Delete',
  SAVE: 'Save',
  CONFIRM: 'Confirm',
} as const;

// Browser empty states
export const EMPTY_STATE = {
  CREATE_WORKSPACE: 'Create a workspace',
  NEW_CARD: 'New card',
  NO_SOURCE_TITLE: 'No workspace docked',
  NO_SOURCE_BODY: 'Create a workspace or find one and dock it in the header above.',
  NO_ARTIFACTS_TITLE: 'Nothing here yet',
  NO_ARTIFACTS_INBOX_BODY: 'This is your Inbox. Create a card right here, drop a file, or double-click an empty space.',
  NO_ARTIFACTS_BODY: 'Create a card, drop a file, or double-click an empty space.',
  NO_SEARCH_RESULTS_TITLE: 'No matches',
  NO_SEARCH_RESULTS_BODY: (query: string) => `Nothing here matches "${query}".`,
  NO_FILTER_RESULTS_BODY: 'The active filters hide every card here.',
  CLEAR_SEARCH: 'Clear search',
  CLEAR_FILTERS: 'Clear filters',
} as const;
