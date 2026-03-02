"use client";

import { useEffect, useState } from "react";
import { getWsUrl } from "@/lib/api";

export function useWebSocket() {
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const url = getWsUrl();
    const ws = new WebSocket(url);
    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onerror = () => setConnected(false);
    return () => ws.close();
  }, []);

  return connected;
}
