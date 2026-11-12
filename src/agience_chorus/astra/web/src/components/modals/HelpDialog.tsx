import { useMemo, useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Separator } from '@/components/ui/separator';
import { PRODUCT_NOUN } from '@/product/copy';
import { GLOSSARY_ENTRIES } from '@/product/help/glossary';
import { useShortcuts } from '@/context/shortcuts/useShortcuts';
import { formatShortcutCombo } from '@/context/shortcuts/shortcut-utils';

type HelpDialogProps = {
  isOpen: boolean;
  onClose: () => void;
  defaultTab?: 'start' | 'glossary' | 'shortcuts';
};

/** Where "Send feedback" writes to: the address the app's privacy and cookie pages name. */
export const FEEDBACK_HREF = 'mailto:connect@agience.ai?subject=Agience%20feedback';

/** The five things a new person does first, in order. */
export const GET_STARTED_STEPS: Array<{ title: string; body: string }> = [
  { title: 'Open a workspace', body: 'A workspace holds your work. Pick one from the sidebar, or make a new one with New workspace.' },
  { title: 'Add a card', body: 'New card adds a note, a file or any other kind of item to the workspace you are in.' },
  { title: 'Group cards in a collection', body: 'A collection gathers related cards. Drag cards into it, or add them from the card menu.' },
  { title: 'Build a workflow', body: 'A workflow runs steps for you. Add a step, choose what it does, and Run now; arm a timer to run it on a schedule.' },
  { title: 'Share it', body: 'Share a workspace or collection with someone, and choose what they may do: read, add or edit.' },
];

/** "a" or "an" for the word that follows. */
export function article(word: string): string {
  return /^[aeiou]/i.test(word) ? 'an' : 'a';
}

export default function HelpDialog({ isOpen, onClose, defaultTab = 'start' }: HelpDialogProps) {
  const [tab, setTab] = useState<string>(defaultTab);
  const { groups, openDialog: openShortcutDialog } = useShortcuts();

  const nounLower = PRODUCT_NOUN.singular.toLowerCase();

  const shortcutHint = useMemo(() => {
    const combos = [formatShortcutCombo('?'), formatShortcutCombo('mod+/')];
    // Render as simple text: "?" or "Ctrl + /"
    const pretty = combos
      .map((parts) => parts.join(' + '))
      .filter(Boolean);
    return pretty.length ? pretty.join(' or ') : '?';
  }, []);

  if (!isOpen) return null;

  return (
    <Dialog open={isOpen} onOpenChange={(open) => (open ? null : onClose())}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Help</DialogTitle>
          <DialogDescription>
            Getting started, definitions and shortcuts for working with {PRODUCT_NOUN.plural.toLowerCase()}.{' '}
            <a href={FEEDBACK_HREF} className="font-medium text-primary hover:underline">Send feedback</a>
          </DialogDescription>
        </DialogHeader>

        <Tabs value={tab} onValueChange={setTab}>
          <TabsList>
            <TabsTrigger value="start">Get started</TabsTrigger>
            <TabsTrigger value="glossary">Glossary</TabsTrigger>
            <TabsTrigger value="shortcuts">Shortcuts</TabsTrigger>
          </TabsList>

          <TabsContent value="start">
            <ol className="mt-3 space-y-3">
              {GET_STARTED_STEPS.map((step, i) => (
                <li key={step.title} className="rounded-lg border border-gray-200 p-4">
                  <h3 className="text-base font-semibold text-foreground">{i + 1}. {step.title}</h3>
                  <p className="text-sm text-muted-foreground mt-1">{step.body}</p>
                </li>
              ))}
            </ol>
          </TabsContent>

          <TabsContent value="glossary">
            <div className="mt-3">
              <p className="text-sm text-muted-foreground">
                In Agience, a “knowledge unit” is just {article(nounLower)} {nounLower}. Different kinds of {PRODUCT_NOUN.plural.toLowerCase()} (decisions, actions, constraints, claims) are represented by metadata and evidence.
              </p>

              <Separator className="my-4" />

              <div className="max-h-[60vh] overflow-y-auto pr-1">
                <ul className="space-y-4">
                  {GLOSSARY_ENTRIES.map((entry) => (
                    <li key={entry.id} className="rounded-lg border border-gray-200 p-4">
                      <div className="flex items-start justify-between gap-4">
                        <div className="min-w-0">
                          <h3 className="text-base font-semibold text-foreground">{entry.term}</h3>
                          {entry.short ? (
                            <p className="text-sm text-muted-foreground mt-1">{entry.short}</p>
                          ) : null}
                        </div>
                        {entry.aka?.length ? (
                          <div className="text-xs text-muted-foreground text-right flex-shrink-0">
                            <div className="font-medium">AKA</div>
                            <div>{entry.aka.join(', ')}</div>
                          </div>
                        ) : null}
                      </div>
                      <p className="text-sm text-foreground mt-3 whitespace-pre-line">{entry.body}</p>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </TabsContent>

          <TabsContent value="shortcuts">
            <div className="mt-3">
              <div className="flex items-start justify-between gap-4">
                <p className="text-sm text-muted-foreground">
                  Press {shortcutHint} any time to open the full keyboard shortcuts panel.
                </p>
                <button
                  type="button"
                  onClick={openShortcutDialog}
                  className="text-sm font-medium text-primary hover:text-primary"
                >
                  Open shortcuts panel
                </button>
              </div>

              <Separator className="my-4" />

              <div className="max-h-[60vh] overflow-y-auto pr-1">
                {groups.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No shortcuts registered yet.</p>
                ) : (
                  <div className="space-y-5">
                    {groups.map((group) => (
                      <div key={group.id}>
                        <h3 className="text-sm font-semibold text-foreground mb-2">{group.title}</h3>
                        <ul className="space-y-2">
                          {group.shortcuts.map((shortcut) => (
                            <li
                              key={shortcut.id}
                              className="flex items-start justify-between gap-4 rounded-md border border-gray-200 p-3"
                            >
                              <div className="flex-1 min-w-0">
                                <p className="text-sm font-medium text-foreground">{shortcut.label}</p>
                                {shortcut.description ? (
                                  <p className="text-xs text-muted-foreground mt-0.5">{shortcut.description}</p>
                                ) : null}
                              </div>
                              <div className="flex flex-wrap gap-2 justify-end">
                                {shortcut.combos.map((combo) => (
                                  <span
                                    key={`${shortcut.id}-${combo}`}
                                    className="inline-flex items-center gap-1 px-2 py-1 text-xs bg-gray-100 border border-gray-300 rounded font-medium text-gray-700"
                                  >
                                    {formatShortcutCombo(combo).join(' + ')}
                                  </span>
                                ))}
                              </div>
                            </li>
                          ))}
                        </ul>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}
