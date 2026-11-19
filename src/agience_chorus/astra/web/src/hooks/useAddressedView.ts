// hooks/useAddressedView.ts
//
// A view held in the address, as one query parameter (`?open=help`, `?layout=list`). Changing it
// pushes a history entry, so Back returns to the previous view inside the app (on a phone, the back
// swipe closes Help instead of leaving the app), and the address can be linked to or reloaded.

import { useCallback, useLayoutEffect, useRef } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';

type Pushed = Record<string, boolean>;

/**
 * `[value, setValue]` for query parameter `key`; `fallback` is the value with no parameter set.
 * `setValue` keeps one identity across renders, so a listener registered once can call it.
 */
export function useAddressedValue<T extends string>(key: string, fallback: T): [T, (next: T) => void] {
  const [params] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const value = (params.get(key) as T | null) ?? fallback;
  const latest = useRef({ location, value });
  useLayoutEffect(() => { latest.current = { location, value }; });

  const setValue = useCallback((next: T) => {
    const { location, value } = latest.current;
    if (next === value) return;
    const pushed = (location.state as { addressed?: Pushed } | null)?.addressed ?? {};
    // Back to the view this one was opened from: step back over our own entry.
    if (next === fallback && pushed[key]) {
      navigate(-1);
      return;
    }
    const search = new URLSearchParams(location.search);
    if (next === fallback) search.delete(key);
    else search.set(key, next);
    const qs = search.toString();
    navigate(
      { pathname: location.pathname, search: qs ? `?${qs}` : '', hash: location.hash },
      next === fallback
        ? { replace: true }
        : { state: { ...(location.state as object | null), addressed: { ...pushed, [key]: true } } },
    );
  }, [fallback, key, navigate]);

  return [value, setValue];
}

/** `[open, setOpen]` for a view addressed as `?<key>=<name>`. */
export function useAddressedFlag(key: string, name: string): [boolean, (open: boolean) => void] {
  const [value, setValue] = useAddressedValue<string>(key, '');
  const setOpen = useCallback((open: boolean) => setValue(open ? name : ''), [name, setValue]);
  return [value === name, setOpen];
}
