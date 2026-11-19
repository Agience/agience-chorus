import { useState, useEffect, useCallback, type ReactNode } from 'react';
import { FiMoon, FiSun, FiUser, FiChevronDown, FiSettings, FiSearch, FiGrid } from 'react-icons/fi';
import { HelpCircle, Link2, MessageCircle, MoreHorizontal, Send, Share2, Trash2 } from 'lucide-react';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { useAuth } from '../../hooks/useAuth';
import { useWorkspace } from '../../hooks/useWorkspace';
import { useWorkspaces } from '@/hooks/useWorkspaces';
import type { ActiveSource } from '../../types/workspace';
import type { Artifact } from '@/context/workspace/workspace.types';
import { IconButton } from '@/components/ui/icon-button';
import SettingsModal from '../modals/SettingsModal';
import { formatShortcutCombo } from '@/context/shortcuts/shortcut-utils';
import HelpDialog from '../modals/HelpDialog';
import TrashDialog from '../modals/TrashDialog';
import { OPEN_TRASH_EVENT } from '@/constants/strings';
import { ShareDialog } from '../common/ShareDialog';
import { CHAT_CONTENT_TYPE } from '@/utils/content-type';
import { useUpgradePrompt } from '@/hooks/useUpgradePrompt';
import { useAddressedFlag } from '@/hooks/useAddressedView';
import { getArtifact } from '@/api/artifacts';

// No 'llm-keys' section: the platform does not expose model selection to the user.
type SettingsSection = 'profile' | 'billing';

type ArtifactOpenOptions = {
  startInEditMode?: boolean;
};

type HeaderBarProps = {
  activeSource: ActiveSource;
  /** Actual sidebar width in pixels so tabs align with the divider */
  sidebarWidthPx?: number;
  /** Whether the panel resize handle is being dragged (to sync divider color). */
  isPanelResizing?: boolean;
  settingsInitialSection?: SettingsSection;
  settingsScopedCollectionId?: string;
  onSettingsSectionClear?: () => void;
  /** Called after a chat artifact is created from the "Ask anything" input. */
  onArtifactCreated?: (artifact: Artifact, options?: ArtifactOpenOptions) => void;
  /**
   * On a narrow viewport, the panel shown and the switch between them. Present, the bar takes its
   * size from the viewport: two rows, Share and Help kept, the other icons in one More menu.
   */
  narrowPanel?: 'left' | 'right';
  onNarrowPanelChange?: (panel: 'left' | 'right') => void;
};

/** A phone-sized target: 44 px square. */
const NARROW_TARGET = 'h-11 w-11';

export default function HeaderBar({
  sidebarWidthPx,
  isPanelResizing = false,
  settingsInitialSection,
  settingsScopedCollectionId,
  onSettingsSectionClear,
  onArtifactCreated,
  narrowPanel,
  onNarrowPanelChange,
}: HeaderBarProps) {
  const narrow = narrowPanel !== undefined;
  const [darkMode, setDarkMode] = useState(false);

  // Each dialog has its own address, so Back closes it and the address can be shared or reloaded.
  const [showSettings, setShowSettings] = useAddressedFlag('open', 'settings');
  const [showHelp, setShowHelp] = useAddressedFlag('open', 'help');
  const [showTrash, setShowTrash] = useAddressedFlag('open', 'trash');
  const [showShare, setShowShare] = useAddressedFlag('open', 'share');

  // Internal section override — used when agience:open-settings event fires
  const [eventSection, setEventSection] = useState<SettingsSection | undefined>(undefined);

  // Mount the 402 upgrade-prompt toast listener
  useUpgradePrompt();
  const { user, logout: signOut } = useAuth() ?? {};
  const shortcutHint = formatShortcutCombo('mod+/').join(' + ');
  const { createArtifact } = useWorkspace();
  const { activeWorkspaceId, workspaces } = useWorkspaces();
  const activeWorkspaceName = workspaces?.find((w) => w.id === activeWorkspaceId)?.name;

  // Open settings modal when initialSection is set from parent
  useEffect(() => {
    if (settingsInitialSection) {
      setShowSettings(true);
    }
  }, [settingsInitialSection, setShowSettings]);

  // Listen for agience:open-settings events (e.g. from the upgrade toast)
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<{ section?: string }>).detail;
      const section = detail?.section as SettingsSection | undefined;
      if (section) setEventSection(section);
      setShowSettings(true);
    };
    window.addEventListener('agience:open-settings', handler);
    return () => window.removeEventListener('agience:open-settings', handler);
  }, [setShowSettings]);

  // Listen for agience:open-trash events (e.g. from the "Moved to Trash" toast)
  useEffect(() => {
    const open = () => setShowTrash(true);
    window.addEventListener(OPEN_TRASH_EVENT, open);
    return () => window.removeEventListener(OPEN_TRASH_EVENT, open);
  }, [setShowTrash]);

  const toggleDarkMode = () => {
    setDarkMode(!darkMode);
    // Toggles local state only; no theme change is wired up to consume it.
  };

  // Through the auth provider: as a service provider it also ends the IdP's session, without which
  // the next visit is handed a new token and signs straight back in. No navigation here: one started
  // now would race the provider's.
  const logout = useCallback(() => {
    signOut?.();
  }, [signOut]);


  // When expanded, match the live sidebar width so the tabs slide with the divider.
  const expandedSidebarWidth = typeof sidebarWidthPx === 'number' && sidebarWidthPx > 0
    ? sidebarWidthPx + 1
    : 256;

  // Quick add — creates a Chat artifact that auto-opens as floating ChatWindow
  const [quickAddText, setQuickAddText] = useState('');
  const canSubmitQuickAdd = Boolean(activeWorkspaceId) && Boolean(quickAddText.trim());

  const handleQuickAddSubmit = useCallback(async () => {
    const text = quickAddText.trim();
    if (!text || !activeWorkspaceId) return;

    try {
      const chatContext = {
        type: 'chat',
        title: text.length > 60 ? text.slice(0, 57) + '...' : text,
        content_type: CHAT_CONTENT_TYPE,
        chat: {
          workspace_id: activeWorkspaceId ?? undefined,
          messages: [{ role: 'user', content: text }],
        },
      };
      const artifact = await createArtifact({
        content: text,
        content_type: CHAT_CONTENT_TYPE,
        context: JSON.stringify(chatContext),
      });
      setQuickAddText('');
      if (artifact && onArtifactCreated) {
        onArtifactCreated(artifact);
      }
    } catch (error) {
      console.error('[HeaderBar] Chat artifact creation failed', error);
    }
  }, [quickAddText, createArtifact, activeWorkspaceId, onArtifactCreated]);

  const handleOpenBindings = useCallback(async () => {
    if (!activeWorkspaceId || !onArtifactCreated) return;
    try {
      const wsArtifact = await getArtifact(activeWorkspaceId);
      onArtifactCreated(wsArtifact);
    } catch (err) {
      console.error('Failed to open bindings:', err);
    }
  }, [activeWorkspaceId, onArtifactCreated]);

  const askInput = (
    <div className={`relative min-w-0 ${narrow ? 'w-full' : 'flex-1 max-w-xl ml-[17px]'}`}>
      <MessageCircle className="absolute left-3 top-1/2 -translate-y-1/2 h-5 w-5 text-gray-400" />
      <input
        value={quickAddText}
        onChange={(e) => setQuickAddText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            void handleQuickAddSubmit();
          }
        }}
        placeholder="Ask anything..."
        className={`w-full min-w-0 pl-11 ${narrow ? 'pr-12 py-3' : 'pr-10 py-2.5'} text-sm border border-border rounded-lg bg-white/95 shadow-sm focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent transition-all placeholder:text-muted-foreground/70 disabled:cursor-not-allowed disabled:opacity-70`}
      />
      <div className={`absolute ${narrow ? 'right-0' : 'right-2'} top-1/2 -translate-y-1/2 flex items-center gap-1`}>
        <button
          onClick={() => void handleQuickAddSubmit()}
          disabled={!canSubmitQuickAdd}
          className={`${narrow ? `${NARROW_TARGET} inline-flex items-center justify-center` : 'p-1'} hover:bg-gray-100 rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed`}
          title={activeWorkspaceId ? 'Send (Enter)' : 'Dock a workspace to save a chat'}
          aria-label="Send"
        >
          <Send className="h-4 w-4 text-gray-500" />
        </button>
      </div>
    </div>
  );

  const dialogs = (
    <>
      <SettingsModal
        isOpen={showSettings}
        onClose={() => {
          setShowSettings(false);
          setEventSection(undefined);
          onSettingsSectionClear?.();
        }}
        initialSection={eventSection ?? settingsInitialSection}
        scopedToCollectionId={settingsScopedCollectionId}
        onArtifactCreated={onArtifactCreated}
      />

      <TrashDialog isOpen={showTrash} onClose={() => setShowTrash(false)} />

      <HelpDialog
        isOpen={showHelp}
        onClose={() => setShowHelp(false)}
        defaultTab="start"
      />

      {activeWorkspaceId && (
        <ShareDialog
          open={showShare}
          onOpenChange={setShowShare}
          workspaceId={activeWorkspaceId}
          workspaceName={activeWorkspaceName}
        />
      )}
    </>
  );

  // Narrow: the bar takes its size from the viewport. Row one holds the logo, the panel switch,
  // Share, Help and one More menu; row two the Ask input, full width. The More menu renders in a
  // portal, above the panels.
  if (narrow) {
    const panelButton = (panel: 'left' | 'right', label: string, icon: ReactNode) => (
      <button
        type="button"
        onClick={() => onNarrowPanelChange?.(panel)}
        aria-pressed={narrowPanel === panel}
        aria-label={label}
        title={label}
        className={`${NARROW_TARGET} inline-flex items-center justify-center transition-colors ${narrowPanel === panel ? 'bg-gray-900 text-white' : 'bg-white text-gray-600 hover:bg-gray-100'}`}
      >
        {icon}
      </button>
    );
    return (
      <header className="flex flex-col w-full min-w-0 bg-white border-b border-gray-200 z-20" data-layout="narrow">
        <div className="flex items-center gap-1 h-14 px-2 min-w-0">
          <img src="/logo_h.png" alt="Agience" className="h-7 min-w-0 shrink object-contain object-left" />
          <div role="group" aria-label="Panel" className="flex flex-shrink-0 overflow-hidden rounded-sm border border-gray-300">
            {panelButton('left', 'Search', <FiSearch className="h-5 w-5" />)}
            {panelButton('right', 'Workspace', <FiGrid className="h-5 w-5" />)}
          </div>
          <div className="flex-1" />
          {activeWorkspaceId && (
            <IconButton size="lg" variant="ghost" className={NARROW_TARGET}
                        onClick={() => setShowShare(true)} title="Share this workspace" aria-label="Share workspace">
              <Share2 />
            </IconButton>
          )}
          <IconButton size="lg" variant="ghost" className={NARROW_TARGET}
                      onClick={() => setShowHelp(true)} title="Help" aria-label="Open help">
            <HelpCircle />
          </IconButton>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <IconButton size="lg" variant="ghost" className={NARROW_TARGET} title="More" aria-label="More">
                <MoreHorizontal />
              </IconButton>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              {user?.email && <div className="px-2 py-2 text-xs text-gray-500 truncate">{user.email}</div>}
              {activeWorkspaceId && (
                <DropdownMenuItem className="min-h-11" onSelect={() => void handleOpenBindings()}>
                  <Link2 className="h-4 w-4" /> Workspace bindings
                </DropdownMenuItem>
              )}
              <DropdownMenuItem className="min-h-11" onSelect={() => setShowTrash(true)}>
                <Trash2 className="h-4 w-4" /> Trash
              </DropdownMenuItem>
              <DropdownMenuItem className="min-h-11" onSelect={toggleDarkMode}>
                {darkMode ? <FiSun className="h-4 w-4" /> : <FiMoon className="h-4 w-4" />}
                {darkMode ? 'Light mode' : 'Dark mode'}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem className="min-h-11" onSelect={() => setShowSettings(true)}>
                <FiSettings className="h-4 w-4" /> Settings
              </DropdownMenuItem>
              <DropdownMenuItem className="min-h-11" onSelect={logout}>
                Log out
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
        <div className="px-2 pb-2 min-w-0">{askInput}</div>
        {dialogs}
      </header>
    );
  }

  return (
    <header className="flex items-center h-16 bg-white border-b border-gray-200 z-20">
      {/* Left Section: Dynamic width matching sidebar */}
      <div
        className={`flex items-center flex-shrink-0 h-full border-r transition-colors ${isPanelResizing ? 'border-purple-500' : 'border-gray-200 hover:border-purple-300'}`}
        style={{ width: `${expandedSidebarWidth}px`, justifyContent: 'flex-start', paddingLeft: '16px', paddingRight: '11px' }}
      >
        <img src="/logo_h.png" alt="Agience" className="h-10" />
      </div>

      {/* Center Section: Ask anything input, aligned with workspace divider and sliding with sidebar */}
      <div className="flex-1 min-w-[16rem] pr-4 flex items-center">
        {askInput}
      </div>

      {/* Right Section: Actions */}
      <div className="flex items-center gap-2 pr-4 flex-shrink-0">
        {/* Bindings — active workspace only */}
        {activeWorkspaceId && (
          <IconButton
            size="lg"
            variant="ghost"
            onClick={handleOpenBindings}
            title="Workspace bindings"
            aria-label="Open workspace bindings"
          >
            <Link2 />
          </IconButton>
        )}

        {/* Share — active workspace only */}
        {activeWorkspaceId && (
          <IconButton
            size="lg"
            variant="ghost"
            onClick={() => setShowShare(true)}
            title="Share this workspace"
            aria-label="Share workspace"
          >
            <Share2 />
          </IconButton>
        )}

        {/* Trash */}
        <IconButton
          size="lg"
          variant="ghost"
          onClick={() => setShowTrash(true)}
          title="Trash"
          aria-label="Open Trash"
        >
          <Trash2 />
        </IconButton>

        {/* Help */}
        <IconButton
          size="lg"
          variant="ghost"
          onClick={() => setShowHelp(true)}
          title={`Help (Shortcuts: ${shortcutHint} or ?)`}
          aria-label="Open help"
        >
          <HelpCircle />
        </IconButton>

        {/* Dark Mode Toggle */}
        <IconButton
          size="lg"
          variant="ghost"
          onClick={toggleDarkMode}
          title={darkMode ? 'Light Mode' : 'Dark Mode'}
        >
          {darkMode ? <FiSun /> : <FiMoon />}
        </IconButton>

        {/* User menu: a portal at the window layer, above the panels. */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              className="flex items-center gap-2 rounded-lg transition-colors group hover:bg-gray-100"
              title="User Menu"
            >
              <div className="h-10 w-10 rounded-sm border border-gray-300 bg-white flex items-center justify-center flex-shrink-0 transition-colors">
                <FiUser className="w-4 h-4 text-gray-500 group-hover:text-gray-900" />
              </div>
              <span className="text-sm font-medium text-gray-500 group-hover:text-gray-900 hidden md:inline transition-colors">
                {user?.name || 'User'}
              </span>
              <FiChevronDown className="w-4 h-4 text-gray-600 hidden md:inline" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            <div className="px-2 py-2 text-sm text-gray-600 truncate">{user?.email}</div>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => setShowSettings(true)}>
              <FiSettings className="w-4 h-4" />
              Settings
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={logout}>Log out</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {dialogs}
    </header>
  );
}