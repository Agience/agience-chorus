import { ReactNode, useState, useEffect, useCallback, useRef } from 'react';
import { CollectionsContext } from './CollectionsContext';
import { Collection } from './collection.types';
import { useAuth } from '../../hooks/useAuth';
import {
  listCollections,
  createCollection,
} from '../../api/collections';
import { ARTIFACT_CHANGED_EVENT, changeOf } from '../../constants/strings';
import { safeParseArtifactContext } from '../../utils/artifactContext';
import { COLLECTION_CONTENT_TYPE } from '../../utils/content-type';

export const CollectionsProvider = ({ children }: { children: ReactNode }) => {
  const { isAuthenticated, loading: authLoading } = useAuth();
  const [collections, setCollections] = useState<Collection[]>([]);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  const hasGrantKeys = (() => {
    // Check grant_keys storage key.
    const raw = sessionStorage.getItem('grant_keys') ?? localStorage.getItem('grant_keys');
    if (!raw) return false;
    try {
      const val = JSON.parse(raw);
      return Array.isArray(val) && val.length > 0;
    } catch {
      return false;
    }
  })();

  useEffect(() => {
    if (authLoading) return;
    if (!isAuthenticated && !hasGrantKeys) return;

    setIsLoading(true);
    listCollections()
      .then(setCollections)
      .catch((err) => {
        console.error('Failed to fetch collections', err);
      })
      .finally(() => setIsLoading(false));
  }, [authLoading, isAuthenticated, hasGrantKeys]);

  // A collection saved or created anywhere in the app is read again, so a rename shows in every
  // list without a reload. 2026-10-29, a tester renamed a collection and Ctrl+K kept the old name.
  const listedRef = useRef<Collection[]>([]);
  listedRef.current = collections;
  useEffect(() => {
    if (authLoading || (!isAuthenticated && !hasGrantKeys)) return;
    const onChange = (e: Event) => {
      const change = changeOf(e);
      if (!change) return;
      const type = (change.content_type as string | undefined) ?? safeParseArtifactContext(change.context).content_type;
      if (type !== COLLECTION_CONTENT_TYPE && !listedRef.current.some(c => String(c.id) === change.id)) return;
      listCollections().then(setCollections).catch(err => console.error('Failed to reload collections', err));
    };
    window.addEventListener(ARTIFACT_CHANGED_EVENT, onChange);
    return () => window.removeEventListener(ARTIFACT_CHANGED_EVENT, onChange);
  }, [authLoading, isAuthenticated, hasGrantKeys]);

  const addSharedCollection = useCallback(async (name: string) => {
    try {
      const created = await createCollection({ name });
      setCollections((prev) => [...prev, created]);
    } catch (err) {
      console.error('Failed to create collection', err);
    }
  }, []);

  const value = {
    collections,
    addSharedCollection,
    isEditModalOpen,
    openEditModal: () => setIsEditModalOpen(true),
    closeEditModal: () => setIsEditModalOpen(false),
    isLoading,
  };

  return (
    <CollectionsContext.Provider value={value}>
      {children}
    </CollectionsContext.Provider>
  );
};
