type CacheEntry<T> = {
  value: T;
  ts: number;
};

const cache = new Map<string, CacheEntry<unknown>>();

export function getCached<T>(key: string, maxAgeMs: number): T | null {
  const entry = cache.get(key);
  if (!entry) return null;
  if (Date.now() - entry.ts > maxAgeMs) {
    cache.delete(key);
    return null;
  }
  return entry.value as T;
}

export function setCached<T>(key: string, value: T): void {
  cache.set(key, { value, ts: Date.now() });
}

