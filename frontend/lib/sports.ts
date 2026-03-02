/** Виды спорта: slug для URL и отображаемое название. */
export const SPORTS = [
  { slug: "table-tennis", name: "Настольный теннис", available: true },
  { slug: "tennis", name: "Теннис", available: false },
  { slug: "football", name: "Футбол", available: false },
  { slug: "basketball", name: "Баскетбол", available: false },
  { slug: "volleyball", name: "Волейбол", available: false },
  { slug: "hockey", name: "Хоккей", available: false },
] as const;

export type SportSlug = (typeof SPORTS)[number]["slug"];

export function getSportBySlug(slug: string): (typeof SPORTS)[number] | undefined {
  return SPORTS.find((s) => s.slug === slug);
}

export function isSportAvailable(slug: string): boolean {
  return getSportBySlug(slug)?.available ?? false;
}
