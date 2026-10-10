import { useContext } from 'react';
import { AuthContext } from '../context/auth/AuthContext';

/** The signed-in user's id, or null outside an AuthProvider or when signed out. */
export const useCurrentUserId = (): string | null => useContext(AuthContext)?.user?.id ?? null;
