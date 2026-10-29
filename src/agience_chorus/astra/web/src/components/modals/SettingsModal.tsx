import { useState, useEffect } from 'react';
import { FiX, FiLoader, FiUser, FiKey, FiCreditCard, FiLink, FiMinusCircle } from 'react-icons/fi';
import { FcGoogle } from 'react-icons/fc';
import { toast } from 'sonner';
// This modal covers profile and billing settings.
// BYOK provider keys and a model picker are omitted because the platform
// does not expose model selection to the user.
import McpSettingsFrame from '../settings/McpSettingsFrame';
import { get } from '../../api/api';
import { useAuth } from '../../hooks/useAuth';
import type { Artifact } from '@/context/workspace/workspace.types';

type ArtifactOpenOptions = {
  startInEditMode?: boolean;
};

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  initialSection?: SettingsSection;
  scopedToCollectionId?: string;
  onArtifactCreated?: (artifact: Artifact, options?: ArtifactOpenOptions) => void;
}

type SettingsSection = 'profile' | 'billing';

interface SettingsSectionConfig {
  id: SettingsSection;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}

const SETTINGS_SECTIONS: SettingsSectionConfig[] = [
  { id: 'profile', label: 'Profile', icon: FiUser },
  { id: 'billing', label: 'Billing', icon: FiCreditCard },
];

export default function SettingsModal({ isOpen, onClose, initialSection }: SettingsModalProps) {
  const [activeSection, setActiveSection] = useState<SettingsSection>(initialSection || 'profile');

  // Update active section when initialSection changes
  useEffect(() => {
    if (initialSection) {
      setActiveSection(initialSection);
    }
  }, [initialSection]);
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-4xl mx-4 h-[80vh] overflow-hidden flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 flex-shrink-0">
          <h2 className="text-xl font-semibold text-gray-900">Settings</h2>
          <button
            onClick={onClose}
            className="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
            title="Close"
          >
            <FiX className="w-5 h-5" />
          </button>
        </div>

        {/* Content: Sidebar + Panel with fixed sizing */}
        <div className="flex-1 flex overflow-hidden min-h-0">
          {/* Sidebar - Fixed Width */}
          <div className="w-56 border-r border-gray-200 bg-gray-50 overflow-y-auto flex-shrink-0">
            <nav className="p-3 space-y-1">
              {SETTINGS_SECTIONS.map((section) => {
                const Icon = section.icon;
                const isActive = activeSection === section.id;
                return (
                  <button
                    key={section.id}
                    onClick={() => setActiveSection(section.id)}
                    className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                      isActive
                        ? 'bg-primary/15 text-primary'
                        : 'text-gray-700 hover:bg-gray-100'
                    }`}
                  >
                    <Icon className="w-5 h-5 flex-shrink-0" />
                    {section.label}
                  </button>
                );
              })}
            </nav>
          </div>

          {/* Content Panel - Fixed size, scrollable content */}
          <div className="flex-1 flex flex-col overflow-hidden">
            <div className="flex-1 overflow-y-auto p-6">
              {activeSection === 'profile' && <ProfileSettings />}
              {activeSection === 'billing' && (
                <McpSettingsFrame
                  server="ophan"
                  resourceUri="ui://ophan/billing-settings.html"
                />
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// Profile Settings Section
function ProfileSettings() {
  const { user, startLinkProvider, unlinkProvider } = useAuth();
  const [googleAvailable, setGoogleAvailable] = useState(false);
  const [unlinkPending, setUnlinkPending] = useState(false);

  useEffect(() => {
    // Check which providers the platform has configured
    get<string[]>('/auth/providers')
      .then((providers) => setGoogleAvailable(providers.includes('google')))
      .catch(() => {/* silent — providers endpoint may not be mounted in all setups */});
  }, []);

  const linkedToGoogle =
    user?.oidc_provider === 'google' && Boolean(user?.oidc_provider);
  const canUnlink = linkedToGoogle && user?.has_password;
  const canLink = googleAvailable && !linkedToGoogle;

  const handleUnlink = async () => {
    setUnlinkPending(true);
    try {
      await unlinkProvider('google');
      toast.success('Google account unlinked.');
    } catch {
      toast.error('Failed to unlink Google account.');
    } finally {
      setUnlinkPending(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold text-gray-900 mb-2">Profile</h3>
        <p className="text-sm text-gray-600">
          Manage your account identity and linked sign-in methods.
        </p>
      </div>

      {/* User info card */}
      <div className="flex items-center gap-4 p-4 bg-gray-50 border border-gray-200 rounded-lg">
        {user?.picture ? (
          <img
            src={user.picture}
            alt={user.name}
            className="w-12 h-12 rounded-full object-cover"
          />
        ) : (
          <div className="w-12 h-12 rounded-full bg-primary/15 flex items-center justify-center">
            <FiUser className="w-6 h-6 text-primary" />
          </div>
        )}
        <div>
          <p className="font-medium text-gray-900">{user?.name}</p>
          <p className="text-sm text-gray-500">{user?.email}</p>
        </div>
      </div>

      {/* Linked sign-in methods */}
      <div>
        <h4 className="text-sm font-semibold text-gray-700 mb-3">Sign-in methods</h4>
        <div className="space-y-2">
          {/* Password (if set) */}
          {user?.has_password && (
            <div className="flex items-center justify-between p-3 bg-gray-50 border border-gray-200 rounded-lg">
              <div className="flex items-center gap-3">
                <FiKey className="w-5 h-5 text-gray-500" />
                <span className="text-sm text-gray-800">Email &amp; Password</span>
              </div>
              <span className="text-xs text-green-600 font-medium px-2 py-0.5 bg-green-50 rounded-full">Active</span>
            </div>
          )}

          {/* Google */}
          {linkedToGoogle ? (
            <div className="flex items-center justify-between p-3 bg-gray-50 border border-gray-200 rounded-lg">
              <div className="flex items-center gap-3">
                <FcGoogle className="w-5 h-5" />
                <span className="text-sm text-gray-800">Google</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-green-600 font-medium px-2 py-0.5 bg-green-50 rounded-full">Linked</span>
                {canUnlink && (
                  <button
                    onClick={handleUnlink}
                    disabled={unlinkPending}
                    className="flex items-center gap-1.5 text-xs text-red-600 hover:text-red-700 border border-red-200 hover:bg-red-50 rounded px-2 py-1 transition-colors disabled:opacity-50"
                  >
                    {unlinkPending ? <FiLoader className="w-3 h-3 animate-spin" /> : <FiMinusCircle className="w-3 h-3" />}
                    Unlink
                  </button>
                )}
              </div>
            </div>
          ) : googleAvailable ? (
            <div className="flex items-center justify-between p-3 bg-gray-50 border border-gray-200 rounded-lg">
              <div className="flex items-center gap-3">
                <FcGoogle className="w-5 h-5" />
                <span className="text-sm text-gray-800">Google</span>
              </div>
              {canLink && (
                <button
                  onClick={() => startLinkProvider('google')}
                  className="flex items-center gap-1.5 text-xs text-primary hover:text-primary border border-primary/30 hover:bg-primary/10 rounded px-2 py-1 transition-colors"
                >
                  <FiLink className="w-3 h-3" />
                  Link account
                </button>
              )}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}


