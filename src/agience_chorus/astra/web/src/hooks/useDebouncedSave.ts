import { useCallback, useEffect, useRef, useState } from 'react';
import toast from 'react-hot-toast';

interface UseDebouncedSaveOptions {
  delay?: number; // Default 2000ms (2 seconds)
  /** Resolves `false` when the store refused the save and the refusal was already reported;
   * the value then stays unsaved. A throw is a failure this hook reports. */
  onSave: (value: string) => Promise<void | boolean>;
  enabled?: boolean; // Allow disabling auto-save
}

interface UseDebouncedSaveResult {
  isSaving: boolean;
  lastSaved: Date | null;
  /** The last save attempt failed, so the editor shows the value as not saved. */
  saveFailed: boolean;
  forceSave: () => Promise<void>;
  /** Mark the current value as already-saved (e.g. after an external sync).
   *  Prevents a redundant debounced save from firing. */
  resetTracking: (syncedValue: string) => void;
}

export function useDebouncedSave(
  value: string,
  options: UseDebouncedSaveOptions
): UseDebouncedSaveResult {
  const { delay = 2000, onSave, enabled = true } = options;
  
  const [isSaving, setIsSaving] = useState(false);
  const [lastSaved, setLastSaved] = useState<Date | null>(null);
  const [saveFailed, setSaveFailed] = useState(false);
  
  const timeoutRef = useRef<NodeJS.Timeout | null>(null);
  const lastValueRef = useRef<string>(value);
  const isSavingRef = useRef(false);
  // Store onSave in a ref so it never appears in the effect dependency array.
  // This prevents the debounce timer from being reset on every render when
  // the caller passes an inline function.
  const onSaveRef = useRef(onSave);
  onSaveRef.current = onSave;
  // The latest value and switch, for the save on unmount below.
  const valueRef = useRef(value);
  valueRef.current = value;
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;

  const resetTracking = useCallback((syncedValue: string) => {
    lastValueRef.current = syncedValue;
    // Cancel any pending debounce for the old value
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  }, []);

  // Force immediate save (bypass debounce)
  const forceSave = useCallback(async () => {
    if (!enabled) return;
    
    // Clear any pending timeout
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }

    // Don't save if already saving
    if (isSavingRef.current) return;

    // Don't save if value hasn't changed since last save
    if (value === lastValueRef.current) return;

    isSavingRef.current = true;
    setIsSaving(true);

    try {
      if ((await onSaveRef.current(value)) === false) {
        setSaveFailed(true);
      } else {
        lastValueRef.current = value;
        setLastSaved(new Date());
        setSaveFailed(false);
      }
    } catch (error) {
      console.error('Save failed:', error);
      setSaveFailed(true);
      toast.error('Failed to save changes. Please try again.');
    } finally {
      isSavingRef.current = false;
      setIsSaving(false);
    }
  }, [value, enabled]);

  // Debounced auto-save effect
  useEffect(() => {
    if (!enabled) return;

    // Don't trigger save if value hasn't changed
    if (value === lastValueRef.current) return;

    // Clear previous timeout
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }

    // Set new timeout for auto-save
    timeoutRef.current = setTimeout(async () => {
      // Double-check we're not already saving
      if (isSavingRef.current) return;

      isSavingRef.current = true;
      setIsSaving(true);

      try {
        if ((await onSaveRef.current(value)) === false) {
          setSaveFailed(true);
        } else {
          lastValueRef.current = value;
          setLastSaved(new Date());
          setSaveFailed(false);
        }
      } catch (error) {
        console.error('Auto-save failed:', error);
        setSaveFailed(true);
        toast.error('Failed to auto-save changes.');
      } finally {
        isSavingRef.current = false;
        setIsSaving(false);
      }
    }, delay);

    // Cleanup on unmount or value change
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, [value, delay, enabled]);

  // An edit still waiting on the debounce when the editor goes away is saved, not dropped.
  useEffect(() => () => {
    if (!enabledRef.current || valueRef.current === lastValueRef.current) return;
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    const pending = valueRef.current;
    lastValueRef.current = pending;
    void onSaveRef.current(pending).catch((error) => {
      console.error('Save on close failed:', error);
      toast.error('Failed to save changes. Please try again.');
    });
  }, []);

  return { isSaving, lastSaved, saveFailed, forceSave, resetTracking };
}
