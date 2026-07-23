import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { authApi, type AuthOrganization, type AuthUser } from "@/api/auth";
import { TOKEN_STORAGE_KEY } from "@/api/client";
import { CHAT_STORAGE_KEY } from "@/context/ChatContext";

interface AuthContextValue {
  user: AuthUser | null;
  organization: AuthOrganization | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  signup: (orgName: string, email: string, password: string, name: string, departmentId?: string) => Promise<void>;
  acceptInvite: (
    token: string,
    email: string,
    password: string,
    name: string,
    departmentId?: string,
  ) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [organization, setOrganization] = useState<AuthOrganization | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const loadMe = async () => {
    try {
      const me = await authApi.me();
      setUser(me.user);
      setOrganization(me.organization);
    } catch {
      localStorage.removeItem(TOKEN_STORAGE_KEY);
      setUser(null);
      setOrganization(null);
    }
  };

  useEffect(() => {
    const token = localStorage.getItem(TOKEN_STORAGE_KEY);
    if (!token) {
      setIsLoading(false);
      return;
    }
    loadMe().finally(() => setIsLoading(false));
  }, []);

  const login = async (email: string, password: string) => {
    const { access_token } = await authApi.login(email, password);
    localStorage.setItem(TOKEN_STORAGE_KEY, access_token);
    await loadMe();
  };

  const signup = async (orgName: string, email: string, password: string, name: string, departmentId?: string) => {
    const { access_token } = await authApi.signup(orgName, email, password, name, departmentId);
    localStorage.setItem(TOKEN_STORAGE_KEY, access_token);
    await loadMe();
  };

  const acceptInvite = async (
    token: string,
    email: string,
    password: string,
    name: string,
    departmentId?: string,
  ) => {
    const { access_token } = await authApi.acceptInvite(token, email, password, name, departmentId);
    localStorage.setItem(TOKEN_STORAGE_KEY, access_token);
    await loadMe();
  };

  const logout = () => {
    localStorage.removeItem(TOKEN_STORAGE_KEY);
    localStorage.removeItem(CHAT_STORAGE_KEY);
    setUser(null);
    setOrganization(null);
  };

  return (
    <AuthContext.Provider
      value={{ user, organization, isLoading, isAuthenticated: !!user, login, signup, acceptInvite, logout }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
