import Link from "next/link";
import { SPORTS } from "@/lib/sports";

export default function SportsPage() {
  const available = SPORTS.filter((s) => s.available);
  const coming = SPORTS.filter((s) => !s.available);

  return (
    <main className="max-w-3xl mx-auto px-4 py-12">
      <Link href="/" prefetch={false} className="text-slate-400 hover:text-white text-sm mb-6 inline-block">← На главную</Link>
      <h1 className="text-3xl font-bold text-white mb-2">Виды спорта</h1>
      <p className="text-slate-400 text-sm mb-8">
        Выберите вид спорта — лайв-сетка и линия с аналитикой.
      </p>
      <div className="space-y-3">
        {available.map((s) => (
          <div
            key={s.slug}
            className="rounded-xl border border-slate-700 bg-slate-800/50 px-5 py-4 flex items-center gap-4 hover:border-teal-500/40 transition-all"
          >
            <span className="text-3xl">🏓</span>
            <div className="flex-1">
              <span className="text-white font-medium">{s.name}</span>
              <p className="text-slate-500 text-sm mt-0.5">Лайв, линия, статистика по игрокам и матчам</p>
            </div>
            <div className="flex gap-2 shrink-0">
              <Link
                href={`/sports/${s.slug}/live`}
                prefetch={false}
                className="px-3 py-1.5 rounded-lg bg-slate-700 text-slate-200 hover:bg-slate-600 text-sm"
              >
                Лайв
              </Link>
              <Link
                href={`/sports/${s.slug}/line`}
                prefetch={false}
                className="px-3 py-1.5 rounded-lg bg-teal-600 text-white hover:bg-teal-500 text-sm"
              >
                Линия
              </Link>
            </div>
          </div>
        ))}
        {coming.map((s) => (
          <div key={s.slug} className="rounded-xl border border-slate-700/80 px-5 py-4 flex items-center gap-4 opacity-70">
            <span className="text-3xl">
              {s.slug === "tennis" ? "🎾" : s.slug === "football" ? "⚽" : s.slug === "basketball" ? "🏀" : s.slug === "volleyball" ? "🏐" : s.slug === "hockey" ? "🏒" : "📋"}
            </span>
            <div className="flex-1">
              <span className="text-slate-400 font-medium">{s.name}</span>
              <p className="text-slate-500 text-sm mt-0.5">В разработке</p>
            </div>
            <span className="text-xs text-slate-500 shrink-0">Скоро</span>
          </div>
        ))}
      </div>
    </main>
  );
}
