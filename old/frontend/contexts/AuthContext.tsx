"use client";

import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import {
  login as apiLogin,
  register as apiRegister,
  loginWithTelegram as apiLoginWithTelegram,
  type TelegramAuthPayload,
} from "@/lib/api";

const TOKEN_KEY = "sport_analyzator_token";

type AuthContextType = {
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<{ message: string; detail: string }>;
  loginWithTelegram: (payload: TelegramAuthPayload) => Promise<void>;
  saveToken: (accessToken: string) => void;
  logout: () => void;
};

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const t = typeof window !== "undefined" ? localStorage.getItem(TOKEN_KEY) : null;
    setToken(t);
    setIsLoading(false);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const { access_token } = await apiLogin(email, password);
    localStorage.setItem(TOKEN_KEY, access_token);
    setToken(access_token);
  }, []);

  const register = useCallback(async (email: string, password: string) => {
    const result = await apiRegister(email, password);
    // No token: user must verify email first
    return result;
  }, []);

  const loginWithTelegram = useCallback(async (payload: TelegramAuthPayload) => {
    const { access_token } = await apiLoginWithTelegram(payload);
    localStorage.setItem(TOKEN_KEY, access_token);
    setToken(access_token);
  }, []);

  const saveToken = useCallback((accessToken: string) => {
    localStorage.setItem(TOKEN_KEY, accessToken);
    setToken(accessToken);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    setToken(null);
  }, []);

  return (
    <AuthContext.Provider
      value={{
        isAuthenticated: !!token,
        isLoading,
        login,
        register,
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
