"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { grantSubscription, fetchSports, type GrantSubscriptionBody, type SportOption } from "@/lib/api";

const ANALYTICS_TARIFFS = [
  { id: "1sport-1d", name: "1 вид спорта · 1 день", price: "99 ₽", desc: "Полная аналитика по одному виду", access_type: "tg_analytics" as const, scope: "one_sport" as const, days: 1 },
  { id: "1sport-7d", name: "1 вид спорта · 7 дней", price: "499 ₽", desc: "Неделя доступа", access_type: "tg_analytics", scope: "one_sport", days: 7 },
  { id: "1sport-30d", name: "1 вид спорта · 30 дней", price: "1 490 ₽", desc: "Месяц, выгоднее", access_type: "tg_analytics", scope: "one_sport", days: 30 },
  { id: "all-1d", name: "Все виды · 1 день", price: "199 ₽", desc: "Вся аналитика на день", access_type: "tg_analytics", scope: "all" as const, days: 1 },
  { id: "all-7d", name: "Все виды · 7 дней", price: "899 ₽", desc: "Неделя, все виды", access_type: "tg_analytics", scope: "all", days: 7 },
  { id: "all-30d", name: "Все виды · 30 дней", price: "2 490 ₽", desc: "Месяц, все виды", access_type: "tg_analytics", scope: "all", days: 30 },
];

const SIGNALS_ONE_SPORT = [
  { id: "signals-1sport-1d", name: "1 вид спорта · 1 день", price: "49 ₽", desc: "Сигналы по одному виду", access_type: "signals" as const, scope: "one_sport" as const, days: 1 },
  { id: "signals-1sport-7d", name: "1 вид спорта · 7 дней", price: "249 ₽", desc: "Неделя рассылки", access_type: "signals", scope: "one_sport", days: 7 },
  { id: "signals-1sport-30d", name: "1 вид спорта · 30 дней", price: "749 ₽", desc: "Месяц по одному виду", access_type: "signals", scope: "one_sport", days: 30 },
];

const SIGNALS_ALL = [
  { id: "signals-all-1d", name: "Все виды · 1 день", price: "99 ₽", desc: "Сигналы по всем видам", access_type: "signals" as const, scope: "all" as const, days: 1 },
  { id: "signals-all-7d", name: "Все виды · 7 дней", price: "449 ₽", desc: "Неделя, все виды", access_type: "signals", scope: "all", days: 7 },
  { id: "signals-all-30d", name: "Все виды · 30 дней", price: "1 290 ₽", desc: "Месяц, все виды", access_type: "signals", scope: "all", days: 30 },
];

const SIGNALS_TARIFFS = [...SIGNALS_ONE_SPORT, ...SIGNALS_ALL];

type Tariff = (typeof ANALYTICS_TARIFFS)[number] | (typeof SIGNALS_ONE_SPORT)[number] | (typeof SIGNALS_ALL)[number];

function getValidUntil(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

export default function PricingPage() {
  const router = useRouter();
  const { isAuthenticated } = useAuth();
  const [sports, setSports] = useState<SportOption[]>([]);
  const [selected, setSelected] = useState<Tariff | null>(null);
  const [sportKey, setSportKey] = useState<string>("table_tennis");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  useEffect(() => {
    fetchSports().then(setSports).catch(() => setSports([{ id: "table_tennis", name: "Настольный теннис" }]));
  }, []);

  const handleChoose = useCallback(
    (t: Tariff) => {
      if (!isAuthenticated) {
        router.push("/login?returnUrl=/pricing");
        return;
      }
      setSelected(t);
      setError(null);
      setSuccess(false);
    },
    [isAuthenticated, router],
  );

  const handleSubmit = useCallback(async () => {
    if (!selected) return;
    if (selected.scope === "one_sport" && !sportKey) {
      setError("Выберите вид спорта");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const body: GrantSubscriptionBody = {
        access_type: selected.access_type,
        scope: selected.scope,
        sport_key: selected.scope === "one_sport" ? sportKey : null,
        valid_until: getValidUntil(selected.days),
      };
      await grantSubscription(body);
      setSuccess(true);
      setTimeout(() => {
        setSelected(null);
        setSuccess(false);
        router.push("/dashboard");
      }, 1500);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка подключения");
    } finally {
      setLoading(false);
    }
  }, [selected, sportKey, router]);

  const handleCloseModal = useCallback(() => {
    if (!loading) setSelected(null);
  }, [loading]);

  return (
    <main className="max-w-4xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold text-white mb-2">Тарифы</h1>
      <p className="text-slate-400 text-sm mb-8">
        Бесплатный аккаунт даёт ограниченную аналитику. Полный доступ — по подписке. В демо можно подключить доступ без оплаты.
      </p>

      <section id="analytics" className="scroll-mt-4 mb-12">
        <h2 className="text-lg font-semibold text-white mb-2">Полная аналитика</h2>
        <p className="text-slate-500 text-sm mb-4">
          Линия, лайв-сетка, углублённая аналитика по матчам. Один вид спорта или все.
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {ANALYTICS_TARIFFS.map((t) => (
            <div
              key={t.id}
              className="rounded-xl border border-slate-700/80 bg-slate-900/60 p-4 flex flex-col"
            >
              <p className="font-medium text-white">{t.name}</p>
              <p className="text-slate-400 text-sm mt-1">{t.desc}</p>
              <p className="mt-3 text-xl font-bold text-teal-400">{t.price}</p>
              <button
                type="button"
                onClick={() => handleChoose(t)}
                className="mt-4 w-full rounded-lg bg-teal-500 py-2 text-sm font-medium text-white hover:bg-teal-400 transition-colors"
              >
                Выбрать
              </button>
            </div>
          ))}
        </div>
        <p className="text-slate-500 text-xs mt-3">Оплата будет подключена позже. Сейчас — демо-подключение.</p>
      </section>

      <section id="signals" className="scroll-mt-4">
        <h2 className="text-lg font-semibold text-white mb-2">Сигналы в Telegram или на почту</h2>
        <p className="text-slate-500 text-sm mb-4">
          Рассылка прогнозов в реальном времени. Один вид спорта или все виды — как и для аналитики.
        </p>
        <p className="text-slate-400 text-sm font-medium mb-2">1 вид спорта</p>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
          {SIGNALS_ONE_SPORT.map((t) => (
            <div
              key={t.id}
              className="rounded-xl border border-slate-700/80 bg-slate-900/60 p-4 flex flex-col"
            >
              <p className="font-medium text-white">{t.name}</p>
              <p className="text-slate-400 text-sm mt-1">{t.desc}</p>
              <p className="mt-3 text-xl font-bold text-amber-400">{t.price}</p>
              <button
                type="button"
                onClick={() => handleChoose(t)}
                className="mt-4 w-full rounded-lg bg-amber-500/90 py-2 text-sm font-medium text-white hover:bg-amber-400 transition-colors"
              >
                Выбрать
              </button>
            </div>
          ))}
        </div>
        <p className="text-slate-400 text-sm font-medium mb-2">Все виды</p>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {SIGNALS_ALL.map((t) => (
            <div
              key={t.id}
              className="rounded-xl border border-slate-700/80 bg-slate-900/60 p-4 flex flex-col"
            >
              <p className="font-medium text-white">{t.name}</p>
              <p className="text-slate-400 text-sm mt-1">{t.desc}</p>
              <p className="mt-3 text-xl font-bold text-amber-400">{t.price}</p>
              <button
                type="button"
                onClick={() => handleChoose(t)}
                className="mt-4 w-full rounded-lg bg-amber-500/90 py-2 text-sm font-medium text-white hover:bg-amber-400 transition-colors"
              >
                Выбрать
              </button>
            </div>
          ))}
        </div>
        <p className="text-slate-500 text-xs mt-3">Укажите Telegram или email при оплате — настроим доставку.</p>
      </section>

      {selected && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70" onClick={handleCloseModal}>
          <div
            className="rounded-2xl border border-slate-600 bg-slate-900 p-6 w-full max-w-md shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-lg font-semibold text-white mb-2">Подключить подписку (демо)</h3>
            <p className="text-slate-400 text-sm mb-4">
              {selected.name} — доступ до {getValidUntil(selected.days)}.
            </p>
            {selected.scope === "one_sport" && (
              <div className="mb-4">
                <label className="block text-slate-400 text-sm mb-1">Вид спорта</label>
                <select
                  value={sportKey}
                  onChange={(e) => setSportKey(e.target.value)}
                  className="w-full rounded-lg border border-slate-600 bg-slate-800 px-3 py-2 text-white"
                >
                  {sports.map((s) => (
                    <option key={s.id} value={s.id}>{s.name}</option>
                  ))}
                </select>
              </div>
            )}
            {error && <p className="text-rose-400 text-sm mb-2">{error}</p>}
            {success && <p className="text-emerald-400 text-sm mb-2">Подписка подключена. Переход на дашборд...</p>}
            <div className="flex gap-2 mt-4">
              <button
                type="button"
                onClick={handleSubmit}
                disabled={loading}
                className="flex-1 rounded-lg bg-teal-500 py-2 text-sm font-medium text-white hover:bg-teal-400 disabled:opacity-50"
              >
                {loading ? "Подключение..." : "Подключить"}
              </button>
              <button
                type="button"
                onClick={handleCloseModal}
                disabled={loading}
                className="rounded-lg border border-slate-600 py-2 px-4 text-slate-300 hover:bg-slate-800 disabled:opacity-50"
              >
                Отмена
              </button>
            </div>
          </div>
        </div>
      )}

      <p className="mt-8 text-center">
        <Link href="/dashboard" className="text-teal-400 hover:underline text-sm">
          ← На дашборд
        </Link>
      </p>
    </main>
  );
}
