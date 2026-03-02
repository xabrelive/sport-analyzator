"use client";

import Link from "next/link";
import Image from "next/image";
import { useEffect, useState } from "react";
import { fetchMatches, fetchSignalsLandingStats, type Match } from "@/lib/api";
import { useWebSocket } from "@/hooks/useWebSocket";
import { LandingMatchRow } from "@/components/LandingMatchRow";

const DEMO_LIVE = 4;
const DEMO_LINE = 4;

function byStartTime(a: Match, b: Match): number {
  return new Date(a.start_time).getTime() - new Date(b.start_time).getTime();
}

export default function LandingPage() {
  const [live, setLive] = useState<Match[]>([]);
  const [line, setLine] = useState<Match[]>([]);
  const [liveLoaded, setLiveLoaded] = useState(false);
  const [lineLoaded, setLineLoaded] = useState(false);
  const [liveError, setLiveError] = useState<string | null>(null);
  const [lineError, setLineError] = useState<string | null>(null);
  const [signalsStats, setSignalsStats] = useState<{
    free_channel: { day: { total: number; won: number; lost: number }; week: { total: number; won: number; lost: number }; month: { total: number; won: number; lost: number } };
    paid_subscription: { day: { total: number; won: number; lost: number }; week: { total: number; won: number; lost: number }; month: { total: number; won: number; lost: number } };
  } | null>(null);
  const [signalsStatsLoaded, setSignalsStatsLoaded] = useState(false);
  const connected = useWebSocket();

  useEffect(() => {
    let cancelled = false;
    setLiveError(null);
    setLineError(null);
    function load() {
      fetchMatches("matches/live")
        .then((d) => {
          if (!cancelled) {
            const list = Array.isArray(d) ? d : [];
            setLive(list.slice().sort(byStartTime).slice(0, DEMO_LIVE));
            setLiveLoaded(true);
            setLiveError(null);
          }
        })
        .catch((e) => {
          if (!cancelled) {
            setLiveLoaded(true);
            setLiveError(e instanceof Error ? e.message : "Ошибка загрузки");
          }
        });
      fetchMatches("matches/upcoming")
        .then((d) => {
          if (!cancelled) {
            const list = Array.isArray(d) ? d : [];
            setLine(list.slice().sort(byStartTime).slice(0, DEMO_LINE));
            setLineLoaded(true);
            setLineError(null);
          }
        })
        .catch((e) => {
          if (!cancelled) {
            setLineLoaded(true);
            setLineError(e instanceof Error ? e.message : "Ошибка загрузки");
          }
        });
    }
    load();
    const t = setInterval(load, 5000); // лайв обновляется на бэке каждые 2–3 сек
    return () => { cancelled = true; clearInterval(t); };
  }, []);

  useEffect(() => {
    fetchSignalsLandingStats()
      .then((data) => {
        setSignalsStats(data);
        setSignalsStatsLoaded(true);
      })
      .catch(() => setSignalsStatsLoaded(true));
  }, []);

  return (
    <main className="min-h-screen bg-slate-950">
      {/* Hero с логотипом */}
      <section className="relative overflow-hidden border-b border-slate-800">
        <div className="absolute inset-0 bg-gradient-to-b from-teal-500/10 via-transparent to-transparent" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_60%_40%_at_50%_0%,rgba(20,184,166,0.15),transparent)]" />
        <div className="relative max-w-5xl mx-auto px-4 py-14 md:py-20 text-center">
          <div className="inline-flex items-center justify-center gap-3 mb-6 animate-fade-in-up opacity-0 [animation-fill-mode:forwards]">
            <Image src="/pingwin-logo.png" alt="" width={64} height={64} className="rounded-2xl" style={{ height: "auto" }} />
            <span className="text-3xl md:text-4xl font-bold text-white">PingWin</span>
          </div>
          <h1 className="text-3xl sm:text-4xl md:text-5xl font-bold text-white tracking-tight mb-4 animate-fade-in-up opacity-0 [animation-delay:0.05s] [animation-fill-mode:forwards]">
            AI-аналитика спорта
          </h1>
          <p className="text-slate-400 text-lg md:text-xl mb-8 max-w-2xl mx-auto leading-relaxed animate-fade-in-up opacity-0 [animation-delay:0.1s] [animation-fill-mode:forwards]">
            Доступ к аналитике по спортивным событиям: лайв, линия, статистика по игрокам.
          </p>
          <div className="flex flex-wrap justify-center gap-3 animate-fade-in-up opacity-0 [animation-delay:0.15s] [animation-fill-mode:forwards]">
            <Link
              href="/register"
              className="inline-flex items-center rounded-xl bg-teal-500 px-8 py-3.5 font-semibold text-white hover:bg-teal-400 transition-all duration-300 shadow-xl shadow-teal-500/20 hover:shadow-teal-400/30 hover:-translate-y-0.5"
            >
              Получить доступ
            </Link>
            <Link
              href="/login"
              className="inline-flex items-center rounded-xl border border-slate-600 px-8 py-3.5 font-medium text-slate-200 hover:border-teal-500/50 hover:text-teal-400 hover:bg-teal-500/5 transition-all duration-300"
            >
              Войти
            </Link>
          </div>
          {connected && (
            <p className="mt-5 text-sm text-teal-400 animate-fade-in opacity-0 [animation-delay:0.25s] [animation-fill-mode:forwards] flex items-center justify-center gap-2">
              <span className="h-2 w-2 rounded-full bg-teal-400 animate-pulse" />
              Данные в реальном времени
            </p>
          )}
        </div>
      </section>

      {/* Лайв и Линия — две отдельные секции, сетка 2 колонки чтобы всё влезало */}
      <section className="py-8 px-4 border-b border-slate-800/80">
        <div className="max-w-5xl mx-auto space-y-10">
          {/* Лайв */}
          <div>
            <div className="flex items-center gap-2 mb-3">
              <span className="flex h-2 w-2 rounded-full bg-red-500 animate-pulse" aria-hidden />
              <h2 className="text-lg font-bold text-white">Сейчас в лайве</h2>
            </div>
            {liveError && (
              <p className="text-rose-400 text-sm mb-3">{liveError}</p>
            )}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {!liveLoaded && !liveError ? (
                <div className="col-span-full py-10 text-center text-slate-500 text-sm">Загрузка...</div>
              ) : live.length === 0 ? (
                <div className="col-span-full py-10 text-center text-slate-500 text-sm">Нет матчей в лайве.</div>
              ) : (
                live.filter((m) => m?.id).map((m) => <LandingMatchRow key={String(m.id)} match={m} isLive blurValues />)
              )}
            </div>
            <p className="mt-3 text-sm text-slate-500">
              <Link href="/register" className="text-teal-400 hover:text-teal-300 font-medium">Зарегистрироваться</Link>
              {" — счёт по сетам и аналитика"}
            </p>
          </div>

          {/* Линия */}
          <div>
            <h2 className="text-lg font-bold text-white mb-3">Линия</h2>
            <p className="text-slate-500 text-sm -mt-2 mb-3">Матчи, которые начнутся в ближайшее время</p>
            {lineError && (
              <p className="text-rose-400 text-sm mb-3">{lineError}</p>
            )}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {!lineLoaded && !lineError ? (
                <div className="col-span-full py-10 text-center text-slate-500 text-sm">Загрузка...</div>
              ) : line.length === 0 ? (
                <div className="col-span-full py-10 text-center text-slate-500 text-sm">Нет матчей в линии.</div>
              ) : (
                line.filter((m) => m?.id).map((m) => <LandingMatchRow key={String(m.id)} match={m} isLive={false} blurValues />)
              )}
            </div>
            <p className="mt-3 text-sm text-slate-500">
              <Link href="/register" className="text-teal-400 hover:text-teal-300 font-medium">Получить доступ</Link>
              {" — коэффициенты и аналитика"}
            </p>
          </div>
        </div>
      </section>

      {/* Как это работает */}
      <section className="py-10 px-4 border-b border-slate-800/80">
        <div className="max-w-5xl mx-auto">
          <h2 className="text-xl font-bold text-white mb-6 text-center">Как это работает</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="rounded-xl border border-slate-700 bg-slate-800/40 p-5 text-center">
              <span className="text-2xl font-bold text-teal-400">1</span>
              <h3 className="font-semibold text-white mt-2">Регистрация</h3>
              <p className="text-slate-400 text-sm mt-1">Создайте аккаунт и получите доступ к лайву и линии</p>
            </div>
            <div className="rounded-xl border border-slate-700 bg-slate-800/40 p-5 text-center">
              <span className="text-2xl font-bold text-teal-400">2</span>
              <h3 className="font-semibold text-white mt-2">Аналитика</h3>
              <p className="text-slate-400 text-sm mt-1">Смотрите счёт по сетам, вероятности и статистику по игрокам</p>
            </div>
            <div className="rounded-xl border border-slate-700 bg-slate-800/40 p-5 text-center">
              <span className="text-2xl font-bold text-teal-400">3</span>
              <h3 className="font-semibold text-white mt-2">Доступ к данным</h3>
              <p className="text-slate-400 text-sm mt-1">Вся аналитика по матчам в одном месте</p>
            </div>
          </div>
        </div>
      </section>

      {/* Способы уведомлений */}
      <section className="py-8 px-4 border-b border-slate-800/80">
        <div className="max-w-5xl mx-auto">
          <h2 className="text-sm font-semibold text-slate-500 uppercase tracking-widest mb-4 text-center">
            Уведомления
          </h2>
          <p className="text-slate-400 text-sm text-center mb-4 max-w-xl mx-auto">
            Выберите вид спорта и получайте уведомления о новой аналитике или отправку избранной аналитики по выбранным каналам.
          </p>
          <div className="flex flex-wrap justify-center gap-4">
            <div className="rounded-xl border border-slate-700 bg-slate-800/50 px-5 py-3.5 flex items-center gap-3 hover:border-teal-500/30 transition-all">
              <span className="text-xl">✈️</span>
              <span className="text-white font-medium">Telegram</span>
              <span className="text-slate-500 text-xs">уведомления о новой аналитике по выбранному виду спорта</span>
            </div>
            <div className="rounded-xl border border-slate-700 bg-slate-800/50 px-5 py-3.5 flex items-center gap-3 hover:border-teal-500/30 transition-all">
              <span className="text-xl">📧</span>
              <span className="text-white font-medium">Email</span>
              <span className="text-slate-500 text-xs">рассылка избранной аналитики на почту</span>
            </div>
          </div>
        </div>
      </section>

      {/* Бонус подписчикам ТГ */}
      <section className="py-8 px-4 border-b border-slate-800/80">
        <div className="max-w-5xl mx-auto">
          <div className="rounded-2xl border border-teal-500/40 bg-teal-500/10 px-6 py-5 text-center">
            <p className="text-white font-semibold">Подписчикам ТГ‑канала PingWin — 1 день аналитики в подарок</p>
            <p className="text-slate-400 text-sm mt-1">Подпишитесь на канал и получите бесплатный день доступа к аналитике</p>
          </div>
        </div>
      </section>

      {/* Статистика: бесплатный ТГ-канал и платная подписка */}
      <section className="py-8 px-4 border-b border-slate-800/80">
        <div className="max-w-5xl mx-auto space-y-10">
          {/* Бесплатный ТГ-канал */}
          <div>
            <h2 className="text-sm font-semibold text-slate-500 uppercase tracking-widest mb-1">
              Бесплатный ТГ-канал
            </h2>
            <p className="text-slate-400 text-sm mb-4">Сколько прогнозов отправлено в бесплатный канал</p>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              {!signalsStatsLoaded ? (
                <div className="col-span-full text-slate-500 text-sm py-4">Загрузка...</div>
              ) : signalsStats ? (
                <>
                  <div className="rounded-xl border border-slate-700 bg-slate-800/50 p-5">
                    <p className="text-slate-500 text-xs font-medium uppercase tracking-wider">За день</p>
                    <p className="text-xl font-bold text-white mt-2">Всего: {signalsStats.free_channel.day.total}</p>
                    <p className="text-teal-400 text-sm mt-1">Угадано: {signalsStats.free_channel.day.won}</p>
                    <p className="text-rose-400/90 text-sm">Не угадано: {signalsStats.free_channel.day.lost}</p>
                  </div>
                  <div className="rounded-xl border border-slate-700 bg-slate-800/50 p-5">
                    <p className="text-slate-500 text-xs font-medium uppercase tracking-wider">За неделю</p>
                    <p className="text-xl font-bold text-white mt-2">Всего: {signalsStats.free_channel.week.total}</p>
                    <p className="text-teal-400 text-sm mt-1">Угадано: {signalsStats.free_channel.week.won}</p>
                    <p className="text-rose-400/90 text-sm">Не угадано: {signalsStats.free_channel.week.lost}</p>
                  </div>
                  <div className="rounded-xl border border-slate-700 bg-slate-800/50 p-5">
                    <p className="text-slate-500 text-xs font-medium uppercase tracking-wider">За месяц</p>
                    <p className="text-xl font-bold text-white mt-2">Всего: {signalsStats.free_channel.month.total}</p>
                    <p className="text-teal-400 text-sm mt-1">Угадано: {signalsStats.free_channel.month.won}</p>
                    <p className="text-rose-400/90 text-sm">Не угадано: {signalsStats.free_channel.month.lost}</p>
                  </div>
                </>
              ) : (
                <div className="col-span-full text-slate-500 text-sm py-4">—</div>
              )}
            </div>
          </div>

          {/* Платная подписка */}
          <div>
            <h2 className="text-sm font-semibold text-slate-500 uppercase tracking-widest mb-1">
              Платная подписка
            </h2>
            <p className="text-slate-400 text-sm mb-4">Сколько прогнозов отправлено подписчикам</p>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              {!signalsStatsLoaded ? (
                <div className="col-span-full text-slate-500 text-sm py-4">Загрузка...</div>
              ) : signalsStats ? (
                <>
                  <div className="rounded-xl border border-slate-700 bg-slate-800/50 p-5">
                    <p className="text-slate-500 text-xs font-medium uppercase tracking-wider">За день</p>
                    <p className="text-xl font-bold text-white mt-2">Всего: {signalsStats.paid_subscription.day.total}</p>
                    <p className="text-teal-400 text-sm mt-1">Угадано: {signalsStats.paid_subscription.day.won}</p>
                    <p className="text-rose-400/90 text-sm">Не угадано: {signalsStats.paid_subscription.day.lost}</p>
                  </div>
                  <div className="rounded-xl border border-slate-700 bg-slate-800/50 p-5">
                    <p className="text-slate-500 text-xs font-medium uppercase tracking-wider">За неделю</p>
                    <p className="text-xl font-bold text-white mt-2">Всего: {signalsStats.paid_subscription.week.total}</p>
                    <p className="text-teal-400 text-sm mt-1">Угадано: {signalsStats.paid_subscription.week.won}</p>
                    <p className="text-rose-400/90 text-sm">Не угадано: {signalsStats.paid_subscription.week.lost}</p>
                  </div>
                  <div className="rounded-xl border border-slate-700 bg-slate-800/50 p-5">
                    <p className="text-slate-500 text-xs font-medium uppercase tracking-wider">За месяц</p>
                    <p className="text-xl font-bold text-white mt-2">Всего: {signalsStats.paid_subscription.month.total}</p>
                    <p className="text-teal-400 text-sm mt-1">Угадано: {signalsStats.paid_subscription.month.won}</p>
                    <p className="text-rose-400/90 text-sm">Не угадано: {signalsStats.paid_subscription.month.lost}</p>
                  </div>
                </>
              ) : (
                <div className="col-span-full text-slate-500 text-sm py-4">—</div>
              )}
            </div>
          </div>
        </div>
      </section>

      {/* Преимущества + цифры */}
      <section className="py-10 px-4 border-b border-slate-800/80">
        <div className="max-w-5xl mx-auto">
          <h2 className="text-xl font-bold text-white mb-6 text-center">Почему PingWin</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="rounded-xl border border-slate-700 bg-slate-800/40 p-4 text-center hover:border-teal-500/30 transition-all">
              <span className="text-2xl">📊</span>
              <p className="text-white font-semibold mt-2">Статистика по игрокам</p>
              <p className="text-slate-500 text-xs mt-0.5">Тренды, форма, история встреч</p>
            </div>
            <div className="rounded-xl border border-slate-700 bg-slate-800/40 p-4 text-center hover:border-teal-500/30 transition-all">
              <span className="text-2xl">⚡</span>
              <p className="text-white font-semibold mt-2">Лайв в реальном времени</p>
              <p className="text-slate-500 text-xs mt-0.5">Счёт по сетам и очкам</p>
            </div>
            <div className="rounded-xl border border-slate-700 bg-slate-800/40 p-4 text-center hover:border-teal-500/30 transition-all">
              <span className="text-2xl">📈</span>
              <p className="text-white font-semibold mt-2">Вероятности по сетам</p>
              <p className="text-slate-500 text-xs mt-0.5">Оценки на основе данных</p>
            </div>
            <div className="rounded-xl border border-slate-700 bg-slate-800/40 p-4 text-center hover:border-teal-500/30 transition-all">
              <span className="text-2xl">🎯</span>
              <p className="text-white font-semibold mt-2">Доступ к аналитике</p>
              <p className="text-slate-500 text-xs mt-0.5">Данные по матчам в реальном времени</p>
            </div>
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="py-12 px-4">
        <div className="max-w-2xl mx-auto text-center rounded-2xl border border-slate-700 bg-slate-800/50 p-8">
          <h2 className="text-xl font-bold text-white mb-2">Готовы смотреть аналитику?</h2>
          <p className="text-slate-400 text-sm mb-6">Регистрация бесплатная. Лайв, линия и статистика по матчам.</p>
          <Link
            href="/register"
            className="inline-flex rounded-xl bg-teal-500 px-8 py-3.5 font-semibold text-white hover:bg-teal-400 transition-all hover:shadow-lg hover:shadow-teal-500/20"
          >
            Зарегистрироваться
          </Link>
        </div>
      </section>

      <p className="text-center text-slate-500 text-xs px-4 py-4 max-w-xl mx-auto">
        Доступ к аналитике по спортивным событиям.
      </p>

      <footer className="border-t border-slate-800 py-6 px-4">
        <div className="max-w-5xl mx-auto flex flex-wrap justify-center gap-6 text-sm text-slate-500">
          <Link href="/sports" className="hover:text-teal-400 transition-colors">Виды спорта</Link>
          <Link href="/terms" className="hover:text-teal-400 transition-colors">Условия</Link>
          <Link href="/rules" className="hover:text-teal-400 transition-colors">Правила</Link>
          <Link href="/about" className="hover:text-teal-400 transition-colors">Как работает</Link>
          <Link href="/disclaimer" className="hover:text-teal-400 transition-colors">Оговорка</Link>
        </div>
      </footer>
    </main>
  );
}
