import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { api, tokenStore, type Role, type SignupInput, type User } from './api';

interface AuthState {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<User>;
  signup: (body: SignupInput) => Promise<User>;
  /** 데모 모드 전용: 비밀번호 없이 해당 역할의 데모 계정으로 입장 */
  switchDemoRole: (role: Role) => Promise<User>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!tokenStore.get()) {
      setLoading(false);
      return;
    }
    api
      .me()
      .then(setUser)
      .catch(() => tokenStore.set(null))
      .finally(() => setLoading(false));
  }, []);

  const start = useCallback(async (session: Promise<{ access_token: string; user: User }>) => {
    const res = await session;
    tokenStore.set(res.access_token);
    setUser(res.user);
    return res.user;
  }, []);
  const login = useCallback((email: string, password: string) => start(api.login(email, password)), [start]);
  const signup = useCallback((body: SignupInput) => start(api.signup(body)), [start]);
  const switchDemoRole = useCallback((role: Role) => start(api.demoSession(role)), [start]);

  const logout = useCallback(() => {
    tokenStore.set(null);
    setUser(null);
  }, []);

  return <AuthContext.Provider value={{ user, loading, login, signup, switchDemoRole, logout }}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('AuthProvider missing');
  return ctx;
}

export const homeFor = (u: User) => (u.role === 'CUSTOMER' ? '/my' : u.role === 'COUNSELOR' ? '/staff' : '/admin');
