"use client";

import type { TableTennisForecastItem } from "@/lib/api";

const STORAGE_KEY = "tt_bet_marks_v1";

type BetMarkStore = Record<string, 1>;

export function forecastMarkKey(item: TableTennisForecastItem): string {
  const idPart = item.id != null ? `id:${String(item.id)}` : `ev:${String(item.event_id || "")}`;
  const channelPart = String(item.channel || "");
  const marketPart = String(item.market || "");
  const sidePart = String(item.pick_side || "");
  const createdPart = String(item.created_at || 0);
  return `${channelPart}|${idPart}|${marketPart}|${sidePart}|${createdPart}`;
}

function loadStore(): BetMarkStore {
  if (typeof window === "undefined") return {};
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== "object") return {};
    return parsed as BetMarkStore;
  } catch {
    return {};
  }
}

function saveStore(store: BetMarkStore): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(STORAGE_KEY, JSON.stringify(store));
}

export function isBetMarked(item: TableTennisForecastItem): boolean {
  const store = loadStore();
  return Boolean(store[forecastMarkKey(item)]);
}

export function getMarkedKeySet(): Set<string> {
  return new Set(Object.keys(loadStore()));
}

export function setBetMarked(item: TableTennisForecastItem, marked: boolean): void {
  const store = loadStore();
  const key = forecastMarkKey(item);
  if (marked) {
    store[key] = 1;
  } else {
    delete store[key];
  }
  saveStore(store);
}

export function setBetMarkedBulk(items: TableTennisForecastItem[], marked: boolean): void {
  const store = loadStore();
  for (const item of items) {
    const key = forecastMarkKey(item);
    if (marked) {
      store[key] = 1;
    } else {
      delete store[key];
    }
  }
  saveStore(store);
}
