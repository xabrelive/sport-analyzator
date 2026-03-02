"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { fetchMeAccess } from "@/lib/api";

/** Лимит матчей в лайве для бесплатных пользователей. */
export const FREE_LIVE_MATCHES_LIMIT = 3;

type SubscriptionContextType = {
  /** Полный доступ к аналитике: линия, весь лайв, без блюра. True, если есть подписка tg_analytics (один вид или все). */
  hasFullAccess: boolean;
  /** Идёт загрузка доступа с бэкенда (только для авторизованных). */
  accessLoading: boolean;
};

const SubscriptionContext = createContext<SubscriptionContextType | null>(null);

export function SubscriptionProvider({ children }: { children: React.ReactNode }) {
  const { isAuthenticated } = useAuth();
  const [hasFullAccess, setHasFullAccess] = useState(false);
  const [accessLoading, setAccessLoading] = useState(false);

  const loadAccess = useCallback(async () => {
    if (!isAuthenticated) {
      setHasFullAccess(false);
      setAccessLoading(false);
      return;
    }
    setAccessLoading(true);
    try {
      const access = await fetchMeAccess();
      setHasFullAccess(access.tg_analytics?.has ?? false);
    } catch {
      setHasFullAccess(false);
    } finally {
      setAccessLoading(false);
    }
  }, [isAuthenticated]);

  useEffect(() => {
    loadAccess();
  }, [loadAccess]);

  return (
    <SubscriptionContext.Provider value={{ hasFullAccess, accessLoading }}>
      {children}
    </SubscriptionContext.Provider>
  );
}

export function useSubscription() {
  const ctx = useContext(SubscriptionContext);
  if (!ctx) return { hasFullAccess: false };
  return ctx;
}
