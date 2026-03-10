"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import {
  login as apiLogin,
  loginByTelegramCode as apiLoginByTelegramCode,
  register as apiRegister,
  verifyEmail as apiVerifyEmail,
  verifyTelegramCode as apiVerifyTelegramCode,
  loginWithTelegram as apiLoginWithTelegram,
  AUTH_TOKEN_STORAGE_KEY,
  type RegisterResult,
  type TelegramAuthPayload,
} from "@/lib/api";
import { clearDashboardBannerDismissed } from "@/components/DashboardBanner";

type AuthContextType = {
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  loginByTelegramCode: (code: string) => Promise<void>;
  register: (
    email: string,
    password: string,
    acceptTerms: boolean,
    acceptPrivacy: boolean
  ) => Promise<RegisterResult>;
  verifyEmail: (email: string, code: string) => Promise<void>;
  verifyTelegramCode: (code: string, acceptTerms: boolean, acceptPrivacy: boolean) => Promise<void>;
  loginWithTelegram: (payload: TelegramAuthPayload) => Promise<void>;
  saveToken: (accessToken: string) => void;
  logout: () => void;
};

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const t =
      typeof window !== "undefined"
        ? localStorage.getItem(AUTH_TOKEN_STORAGE_KEY)
        : null;
    setToken(t);
    setIsLoading(false);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const { access_token } = await apiLogin(email, password);
    localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, access_token);
    setToken(access_token);
  }, []);

  const loginByTelegramCode = useCallback(async (code: string) => {
    const { access_token } = await apiLoginByTelegramCode(code);
    localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, access_token);
    setToken(access_token);
  }, []);

  const register = useCallback(
    async (
      email: string,
      password: string,
      acceptTerms: boolean,
      acceptPrivacy: boolean
    ) => {
      const result = await apiRegister(email, password, acceptTerms, acceptPrivacy);
      return result;
    },
    []
  );

  const verifyEmail = useCallback(async (email: string, code: string) => {
    const { access_token } = await apiVerifyEmail(email, code);
    localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, access_token);
    setToken(access_token);
  }, []);

  const verifyTelegramCode = useCallback(
    async (code: string, acceptTerms: boolean, acceptPrivacy: boolean) => {
      const { access_token } = await apiVerifyTelegramCode(
        code,
        acceptTerms,
        acceptPrivacy
      );
      localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, access_token);
      setToken(access_token);
    },
    []
  );

  const loginWithTelegram = useCallback(
    async (payload: TelegramAuthPayload) => {
      const { access_token } = await apiLoginWithTelegram(payload);
      localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, access_token);
      setToken(access_token);
    },
    []
  );

  const saveToken = useCallback((accessToken: string) => {
    localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, accessToken);
    setToken(accessToken);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
    clearDashboardBannerDismissed();
    setToken(null);
  }, []);

  return (
    <AuthContext.Provider
      value={{
        isAuthenticated: !!token,
        isLoading,
        login,
        loginByTelegramCode,
        register,
        verifyEmail,
        verifyTelegramCode,
        loginWithTelegram,
        saveToken,
        logout,
      }}
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
