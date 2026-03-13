"use client";

import { useEffect, useRef, useState } from "react";
import { getWsUrl } from "@/lib/api";

type WsMessage = {
  type?: string;
  mode?: string;
  count?: number;
  match_ids?: string[];
  ts?: string;
};

type Listener = (message: WsMessage) => void;

let sharedSocket: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let heartbeatTimer: ReturnType<typeof setInterval> | null = null;
let isStopped = false;
let isConnected = false;
let wsCandidates: string[] = [];
let wsCandidateIndex = 0;
let reconnectDelayMs = 1500;
const RECONNECT_MAX_DELAY_MS = 20_000;
const listeners = new Set<Listener>();
const statusListeners = new Set<(connected: boolean) => void>();

function notifyStatus(next: boolean): void {
  isConnected = next;
  for (const listener of statusListeners) listener(next);
}

function buildWsCandidates(): string[] {
  const primary = getWsUrl();
  const out = [primary];
  if (typeof window !== "undefined") {
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    out.push(`${proto}://${window.location.host}/ws`);
  } else {
    out.push("ws://localhost:12000/ws");
  }
  return Array.from(new Set(out.filter(Boolean)));
}

function ensureSharedConnection(): void {
  if (sharedSocket && (sharedSocket.readyState === WebSocket.OPEN || sharedSocket.readyState === WebSocket.CONNECTING)) {
    return;
  }
  isStopped = false;
  if (wsCandidates.length === 0) {
    wsCandidates = buildWsCandidates();
    wsCandidateIndex = 0;
  }
  const url = wsCandidates[Math.min(wsCandidateIndex, wsCandidates.length - 1)];
  let opened = false;
  sharedSocket = new WebSocket(url);
  sharedSocket.onopen = () => {
    opened = true;
    wsCandidateIndex = 0;
    reconnectDelayMs = 1500;
    notifyStatus(true);
    if (heartbeatTimer) clearInterval(heartbeatTimer);
    heartbeatTimer = setInterval(() => {
      if (!sharedSocket || sharedSocket.readyState !== WebSocket.OPEN) return;
      try {
        // Keepalive ping for proxies/timeouts; backend ignores payload.
        sharedSocket.send("ping");
      } catch {
        sharedSocket?.close();
      }
    }, 20_000);
  };
  sharedSocket.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data) as WsMessage;
      for (const listener of listeners) listener(payload);
    } catch {
      // Ignore malformed payload.
    }
  };
  sharedSocket.onclose = () => {
    notifyStatus(false);
    if (heartbeatTimer) {
      clearInterval(heartbeatTimer);
      heartbeatTimer = null;
    }
    sharedSocket = null;
    if (!opened && wsCandidates.length > 1 && wsCandidateIndex < wsCandidates.length - 1) {
      wsCandidateIndex += 1;
    }
    if (!isStopped) {
      reconnectTimer = setTimeout(ensureSharedConnection, reconnectDelayMs);
      reconnectDelayMs = Math.min(RECONNECT_MAX_DELAY_MS, Math.floor(reconnectDelayMs * 1.8));
    }
  };
  sharedSocket.onerror = () => {
    notifyStatus(false);
    sharedSocket?.close();
  };
}

export function useWebSocket(onMessage?: (message: WsMessage) => void) {
  const [connected, setConnected] = useState(isConnected);
  const callbackRef = useRef(onMessage);

  useEffect(() => {
    callbackRef.current = onMessage;
  }, [onMessage]);

  useEffect(() => {
    const messageListener: Listener = (message) => callbackRef.current?.(message);
    listeners.add(messageListener);
    statusListeners.add(setConnected);
    setConnected(isConnected);
    ensureSharedConnection();

    return () => {
      listeners.delete(messageListener);
      statusListeners.delete(setConnected);
      if (listeners.size === 0 && statusListeners.size === 0) {
        isStopped = true;
        if (reconnectTimer) {
          clearTimeout(reconnectTimer);
          reconnectTimer = null;
        }
        if (heartbeatTimer) {
          clearInterval(heartbeatTimer);
          heartbeatTimer = null;
        }
        sharedSocket?.close();
        sharedSocket = null;
        wsCandidates = [];
        wsCandidateIndex = 0;
        reconnectDelayMs = 1500;
      }
    };
  }, []);

  return connected;
}
