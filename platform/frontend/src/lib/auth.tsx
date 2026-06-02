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
  createUserWithEmailAndPassword,
  onAuthStateChanged,
  signInWithEmailAndPassword,
  signInWithPopup,
  signOut as fbSignOut,
  updateProfile,
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
  name?: string;
}

export type AuthStatus =
  | "loading" // /api/auth/me 応答待ち
  | "authorized" // allowed_users 登録済み & active
  | "deactivated" // allowed_users にいるが active=False (admin による無効化)
  | "pending" // pending_users にいる
  | "unregistered"; // どこにもいない

export interface PendingInfo {
  requested_team_name: string;
}

interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  signIn: () => Promise<void>;
  signInWithEmail: (email: string, password: string) => Promise<void>;
  signUpWithEmail: (
    email: string,
    password: string,
    displayName?: string,
  ) => Promise<void>;
  signOut: () => Promise<void>;
  getIdToken: () => Promise<string | null>;
  // multi-team
  teams: TeamMembership[];
  currentTeam: string | null;
  setCurrentTeam: (team: string) => void;
  // signup state
  authStatus: AuthStatus;
  pendingInfo: PendingInfo | null;
  refreshAuthStatus: () => Promise<void>;
  // legacy global role (allowed_users.role)
  role: string;
  // admin UI 表示の判定用。super-admin もしくは何らかの team の admin。
  // backend `/api/auth/me` の `is_admin` を反映。
  isAdmin: boolean;
  // welcome panel (初回ログイン)
  showWelcome: boolean;
  dismissWelcome: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);
const TEAM_STORAGE_KEY = "labvault.currentTeam";

// build-time env flag: ローカル開発で Firebase 認証を完全に bypass する。
// 立っている時は AuthProvider が Firebase に触らず、固定の dev user / admin
// / konishi-lab を返す。backend 側も LABVAULT_DEV_SKIP_AUTH=1 で起動して
// おくこと (こちらは /api/auth/me に dev_skip ガードがある)。
//
// 本番 build では NEXT_PUBLIC_DEV_SKIP_AUTH を立てないこと。Next.js は
// NEXT_PUBLIC_* を build-time に bundle するため、未定義なら自動的に
// false 扱い。
const DEV_SKIP_AUTH = process.env.NEXT_PUBLIC_DEV_SKIP_AUTH === "1";

const DEV_USER: AuthUser = {
  uid: "dev",
  email: "dev@local",
  displayName: "Dev User",
  photoURL: null,
};

const DEV_TEAMS: TeamMembership[] = [
  { team_id: "konishi-lab", role: "admin", name: "Konishi Lab" },
];

function DevSkipAuthProvider({ children }: { children: ReactNode }) {
  // dev_skip 時の固定 context。Firebase に一切触らない。
  const noop = useCallback(async () => {}, []);
  const noopToken = useCallback(async () => "dev-skip", []);
  const value: AuthContextValue = {
    user: DEV_USER,
    loading: false,
    signIn: noop,
    signInWithEmail: noop as unknown as (
      email: string,
      password: string,
    ) => Promise<void>,
    signUpWithEmail: noop as unknown as (
      email: string,
      password: string,
      displayName?: string,
    ) => Promise<void>,
    signOut: noop,
    getIdToken: noopToken,
    teams: DEV_TEAMS,
    currentTeam: "konishi-lab",
    setCurrentTeam: () => {},
    authStatus: "authorized",
    pendingInfo: null,
    refreshAuthStatus: noop,
    role: "admin",
    isAdmin: true,
    showWelcome: false,
    dismissWelcome: noop,
  };
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

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
  if (DEV_SKIP_AUTH) {
    return <DevSkipAuthProvider>{children}</DevSkipAuthProvider>;
  }
  return <FirebaseAuthProvider>{children}</FirebaseAuthProvider>;
}

function FirebaseAuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [teams, setTeams] = useState<TeamMembership[]>([]);
  const [currentTeam, setCurrentTeamState] = useState<string | null>(null);
  const [authStatus, setAuthStatus] = useState<AuthStatus>("loading");
  const [pendingInfo, setPendingInfo] = useState<PendingInfo | null>(null);
  const [role, setRole] = useState<string>("");
  const [isAdmin, setIsAdmin] = useState<boolean>(false);
  const [showWelcome, setShowWelcome] = useState<boolean>(false);

  useEffect(() => {
    const auth = getFirebaseAuth();
    const unsub = onAuthStateChanged(auth, (u) => {
      setUser(toAuthUser(u));
      if (!u) {
        setTeams([]);
        setCurrentTeamState(null);
        setAuthStatus("loading");
        setPendingInfo(null);
        setRole("");
        setIsAdmin(false);
      }
      setLoading(false);
    });
    return unsub;
  }, []);

  const signIn = useCallback(async () => {
    await signInWithPopup(getFirebaseAuth(), googleProvider);
  }, []);

  const signInWithEmail = useCallback(
    async (email: string, password: string) => {
      await signInWithEmailAndPassword(getFirebaseAuth(), email, password);
    },
    [],
  );

  const signUpWithEmail = useCallback(
    async (email: string, password: string, displayName?: string) => {
      const cred = await createUserWithEmailAndPassword(
        getFirebaseAuth(),
        email,
        password,
      );
      if (displayName && cred.user) {
        await updateProfile(cred.user, { displayName });
      }
    },
    [],
  );

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

  const fetchAuthStatus = useCallback(async () => {
    const token = await getIdToken();
    if (!token) {
      setAuthStatus("loading");
      return;
    }
    const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    const res = await fetch(`${base}/api/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) {
      // 認証失敗 (token invalid / verify error) — loading 維持
      return;
    }
    const me = (await res.json()) as {
      status: AuthStatus;
      teams?: TeamMembership[];
      default_team?: string;
      role?: string;
      is_admin?: boolean;
      requested_team_name?: string;
      show_welcome?: boolean;
    };
    setAuthStatus(me.status);
    if (me.status === "authorized") {
      const ts = me.teams ?? [];
      setTeams(ts);
      setRole(me.role ?? "");
      setIsAdmin(Boolean(me.is_admin));
      setShowWelcome(Boolean(me.show_welcome));
      const stored =
        typeof window !== "undefined"
          ? window.localStorage.getItem(TEAM_STORAGE_KEY)
          : null;
      const initial =
        stored && ts.some((t) => t.team_id === stored)
          ? stored
          : me.default_team || ts[0]?.team_id || null;
      if (initial) setCurrentTeamState(initial);
      setPendingInfo(null);
    } else if (me.status === "pending") {
      setTeams([]);
      setRole("");
      setIsAdmin(false);
      setShowWelcome(false);
      setCurrentTeamState(null);
      setPendingInfo({
        requested_team_name: me.requested_team_name ?? "",
      });
    } else {
      // unregistered / deactivated
      setTeams([]);
      setRole("");
      setIsAdmin(false);
      setShowWelcome(false);
      setCurrentTeamState(null);
      setPendingInfo(null);
    }
  }, [getIdToken]);

  const dismissWelcome = useCallback(async () => {
    const token = await getIdToken();
    if (!token) return;
    const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    try {
      await fetch(`${base}/api/auth/welcome-acknowledged`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
    } catch {
      // ignore — backend が落ちていても UI は閉じる
    }
    setShowWelcome(false);
  }, [getIdToken]);

  // user 確定後に /api/auth/me を呼んで status を更新
  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    (async () => {
      try {
        await fetchAuthStatus();
      } catch {
        if (!cancelled) {
          // ignore — UI 側でハンドリング
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user, fetchAuthStatus]);

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        signIn,
        signInWithEmail,
        signUpWithEmail,
        signOut,
        getIdToken,
        teams,
        currentTeam,
        setCurrentTeam,
        authStatus,
        pendingInfo,
        refreshAuthStatus: fetchAuthStatus,
        role,
        isAdmin,
        showWelcome,
        dismissWelcome,
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
