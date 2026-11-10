import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { ApiError, type User } from "../api/client";
import { api } from "../api/instance";
import { ensureDonor, NotADonorError } from "./rules";
import { secureStore } from "./storage";

type Status = "loading" | "signedOut" | "signedIn";

type AuthState = {
  status: Status;
  user: User | null;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

const isRejection = (error: unknown): boolean =>
  error instanceof ApiError && (error.status === 401 || error.status === 403);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>("loading");
  const [user, setUser] = useState<User | null>(null);

  const signOut = useCallback(async () => {
    await api.logout();
    setUser(null);
    setStatus("signedOut");
  }, []);

  // The server rejected the refresh token while the app was in use.
  useEffect(
    () =>
      api.onSessionEnded(() => {
        setUser(null);
        setStatus("signedOut");
      }),
    [],
  );

  // On start: open from the cached login at once (also offline), then check it in the background.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const session = await secureStore.load();
      if (!session) {
        if (!cancelled) setStatus("signedOut");
        return;
      }
      try {
        if (session.user) {
          ensureDonor(session.user);
          if (cancelled) return;
          setUser(session.user);
          setStatus("signedIn");
        }
        const fresh = await api.refreshUser();
        ensureDonor(fresh);
        if (!cancelled) {
          setUser(fresh);
          setStatus("signedIn");
        }
      } catch (error) {
        if (cancelled) return;
        if (error instanceof NotADonorError || isRejection(error)) {
          await signOut();
        } else if (!session.user) {
          setStatus("signedOut"); // nothing cached and no network
        }
        // Otherwise: offline with a cached login. Stay signed in.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [signOut]);

  const signIn = useCallback(async (email: string, password: string) => {
    const signedIn = await api.login(email, password, ensureDonor);
    setUser(signedIn);
    setStatus("signedIn");
  }, []);

  const value = useMemo(() => ({ status, user, signIn, signOut }), [status, user, signIn, signOut]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}
