"use client";

const SIGNAL_SETTINGS_KEY = "me:signal_settings";

export interface SignalSettings {
  /** Режим тишины: не присылать сигналы в указанный интервал (по местному времени). */
  quiet_mode_enabled: boolean;
  /** Начало интервала тишины (HH:mm). */
  quiet_start: string;
  /** Конец интервала тишины (HH:mm). */
  quiet_end: string;
}

const defaults: SignalSettings = {
  quiet_mode_enabled: false,
  quiet_start: "22:00",
  quiet_end: "08:00",
};

export function getSignalSettings(): SignalSettings {
  if (typeof window === "undefined") return defaults;
  try {
    const raw = localStorage.getItem(SIGNAL_SETTINGS_KEY);
    if (!raw) return defaults;
    const parsed = JSON.parse(raw) as Partial<SignalSettings>;
    return { ...defaults, ...parsed };
  } catch {
    return defaults;
  }
}

export function setSignalSettings(settings: Partial<SignalSettings>): void {
  if (typeof window === "undefined") return;
  try {
    const current = getSignalSettings();
    const next = { ...current, ...settings };
    localStorage.setItem(SIGNAL_SETTINGS_KEY, JSON.stringify(next));
  } catch {
    // ignore
  }
}
