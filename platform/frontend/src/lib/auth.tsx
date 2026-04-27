"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import {
  onAuthStateChanged,
  signInWithPopup,
  signOut as fbSignOut,
  type User as FirebaseUser,
} from "firebase/auth";
import { getFirebaseAuth, googleProvider } from "./firebase";

export interface AuthUser {
  uid: string;
  email: string;
  displayName: string;
  photoURL: string | null;
}

export interface TeamMembership {
  team_id: string;
  role: string;
}

interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  signIn: () => Promise<void>;
  signOut: () => Promise<void>;
  getIdToken: () => Promise<string | null>;
  // multi-team
  teams: TeamMembership[];
  currentTeam: string | null;
  setCurrentTeam: (team: string) => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);
const TEAM_STORAGE_KEY = "labvault.currentTeam";

function toAuthUser(u: FirebaseUser | null): AuthUser | null {
  if (!u) return null;
  return {
    uid: u.uid,
    email: u.email ?? "",
    displayName: u.displayName ?? u.email ?? u.uid,
    photoURL: u.photoURL ?? null,
  };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [teams, setTeams] = useState<TeamMembership[]>([]);
  const [currentTeam, setCurrentTeamState] = useState<string | null>(null);

  useEffect(() => {
    const auth = getFirebaseAuth();
    const unsub = onAuthStateChanged(auth, (u) => {
      setUser(toAuthUser(u));
      if (!u) {
        setTeams([]);
        setCurrentTeamState(null);
      }
      setLoading(false);
    });
    return unsub;
  }, []);

  const signIn = useCallback(async () => {
    await signInWithPopup(getFirebaseAuth(), googleProvider);
  }, []);

  const signOut = useCallback(async () => {
    await fbSignOut(getFirebaseAuth());
  }, []);

  const getIdToken = useCallback(async () => {
    const u = getFirebaseAuth().currentUser;
    if (!u) return null;
    return u.getIdToken();
  }, []);

  const setCurrentTeam = useCallback((team: string) => {
    setCurrentTeamState(team);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(TEAM_STORAGE_KEY, team);
    }
  }, []);

  // user 確定後に /api/auth/me から teams を取得して反映
  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    (async () => {
      try {
        const token = await getIdToken();
        if (!token) return;
        const base =
          process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
        const res = await fetch(`${base}/api/auth/me`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok || cancelled) return;
        const me = (await res.json()) as {
          teams?: TeamMembership[];
          default_team?: string;
        };
        const ts = me.teams ?? [];
        setTeams(ts);
        const stored =
          typeof window !== "undefined"
            ? window.localStorage.getItem(TEAM_STORAGE_KEY)
            : null;
        const initial =
          stored && ts.some((t) => t.team_id === stored)
            ? stored
            : me.default_team || ts[0]?.team_id || null;
        if (initial) setCurrentTeamState(initial);
      } catch {
        // ignore — UI gate 側でハンドリング
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user, getIdToken]);

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        signIn,
        signOut,
        getIdToken,
        teams,
        currentTeam,
        setCurrentTeam,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
