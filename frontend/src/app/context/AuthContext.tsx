import React, { createContext, useContext, useEffect, useState } from 'react';
import {
  clearToken,
  fetchCurrentUser,
  handleOAuthCallback,
  type AuthUser,
} from '../lib/auth';

interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  setUser: (user: AuthUser | null) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export const AuthProvider = ({ children }: { children: React.ReactNode }) => {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      const callbackUser = await handleOAuthCallback().catch(() => null);
      if (callbackUser) {
        setUser(callbackUser);
        setLoading(false);
        return;
      }
      const existingUser = await fetchCurrentUser().catch(() => null);
      setUser(existingUser);
      setLoading(false);
    })();
  }, []);

  const logout = () => {
    clearToken();
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, loading, setUser, logout }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth는 AuthProvider 내부에서만 사용할 수 있습니다.');
  return ctx;
};
