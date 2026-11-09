import { createContext } from "react";
import { User } from "./auth.types";

export interface AuthContextType {
  isAuthenticated: boolean;
  user: User | null;
  login: (provider?: string, setupOperatorToken?: string) => void;
  startLinkProvider: (provider: string) => void;
  unlinkProvider: (provider: string) => Promise<void>;
  logout: () => void;
  /** Ends the local session (stored token, cached identity) and starts a fresh sign-in at Origin. */
  signInAgain: () => void;
  loading: boolean;
  setAuthData: (token: string | null) => void;
  refreshUser: () => void;
}

export const AuthContext = createContext<AuthContextType | undefined>(undefined);


