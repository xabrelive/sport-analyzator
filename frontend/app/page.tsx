"use client";

import Link from "next/link";
import Image from "next/image";
import { Header } from "@/components/Header";
import { Footer } from "@/components/Footer";

const FEATURES = [
  {
    icon: "📊",
    title: "Статистика по игрокам",
    text: "Форма, история встреч, тренды — только факты, без советов.",
  },
  {
    icon: "⚡",
    title: "Лайв",
    text: "Счёт по сетам и очкам в реальном времени и линия предстоящих матчей.",
  },
  {
    icon: "📈",
    title: "Вероятности по сетам",
    text: "Оценки на основе данных. Информация носит справочный характер.",
  },
  {
    icon: "🔔",
    title: "Уведомления",
    text: "Telegram и email по выбранным видам спорта и событиям.",
  },
  {
    icon: "🎯",
    title: "Всё в одном месте",
    text: "Лайв, линия, результаты и статистика — один кабинет, без переключения между сервисами.",
  },
  {
    icon: "🛡️",
    title: "Прозрачность",
    text: "Чёткие правила использования и политика конфиденциальности. Никаких скрытых условий.",
  },
];

const TRUST = [
  { value: "Только аналитика", label: "Без призывов к ставкам" },
  { value: "Почта и Telegram", label: "Один аккаунт" },
  { value: "pingwin.pro", label: "Прозрачные правила" },
];

const HOW_IT_WORKS = [
  { step: 1, title: "Регистрация", text: "Почта или Telegram — за минуту.", icon: "✉️" },
  { step: 2, title: "Аналитика", text: "Лайв, линия, статистика по игрокам и матчам.", icon: "📐" },
  { step: 3, title: "Уведомления", text: "Получайте обновления в Telegram или на почту.", icon: "🔔" },
];

const WHY_US = [
  { title: "Только данные", text: "Никаких рекомендаций «ставить» — только цифры и факты для вашего анализа." },
  { title: "Удобный доступ", text: "Один аккаунт с любого устройства. Уведомления туда, куда вам удобно." },
  { title: "Оперативность", text: "Обновления по матчам и событиям по мере поступления данных от источников." },
];

export default function HomePage() {
  return (
    <>
      <Header />
      <main className="min-h-screen overflow-hidden">
        {/* Hero — компактный */}
        <section className="relative flex flex-col items-center justify-center border-b border-slate-800/60 px-4 py-12 sm:py-14 md:py-16">
          <div className="absolute inset-0 bg-mesh-dark" />
          <div className="absolute inset-0 bg-[radial-gradient(ellipse_80%_50%_at_50%_-20%,rgba(6,182,212,0.12),transparent)]" />
          <div className="relative z-10 flex flex-col items-center text-center stagger">
            <div className="animate-float mb-4">
              <Image
                src="/pingwin-logo.png"
                alt="PingWin"
                width={64}
                height={64}
                className="rounded-xl drop-shadow-lg"
              />
            </div>
            <h1 className="font-display text-3xl font-bold tracking-tight text-white sm:text-4xl md:text-5xl">
              <span className="gradient-text">PingWin</span>
            </h1>
            <p className="mt-2 text-slate-400 text-base sm:text-lg max-w-2xl">
              Спортивная аналитика: лайв, линия, статистика. Только данные — решения за вами.
            </p>
            <p className="mt-0.5 text-slate-500 text-sm">
              pingwin.pro
            </p>
            <div className="mt-6 flex flex-wrap justify-center gap-3">
              <Link
                href="/register"
                className="hover-lift card-glow inline-flex items-center rounded-xl bg-cyan-500 px-6 py-3 font-medium text-white shadow-lg shadow-cyan-500/25 transition hover:bg-cyan-400 hover:shadow-cyan-400/30"
              >
                Начать бесплатно
              </Link>
              <Link
                href="/login"
                className="hover-lift inline-flex items-center rounded-xl border border-slate-600 px-6 py-3 font-medium text-slate-200 transition hover:border-cyan-500/50 hover:bg-cyan-500/10 hover:text-cyan-400"
              >
                Войти
              </Link>
            </div>
          </div>
        </section>

        {/* Trust strip */}
        <section className="border-b border-slate-800/60 py-8 px-4">
          <div className="mx-auto max-w-4xl">
            <div className="grid grid-cols-1 gap-6 sm:grid-cols-3">
              {TRUST.map((item, i) => (
                <div
                  key={i}
                  className="text-center animate-fade-in-up opacity-0 [animation-fill-mode:forwards] [animation-delay:0.1s]"
                  style={{ animationDelay: `${0.1 + i * 0.08}s` }}
                >
                  <p className="font-display text-lg font-semibold text-white">
                    {item.value}
                  </p>
                  <p className="mt-0.5 text-sm text-slate-500">{item.label}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Features */}
        <section className="border-b border-slate-800/60 py-12 px-4 sm:py-14">
          <div className="mx-auto max-w-5xl">
            <h2 className="font-display text-2xl font-semibold text-white text-center sm:text-3xl">
              Что внутри
            </h2>
            <p className="mt-2 text-center text-slate-400 max-w-xl mx-auto">
              Инструменты для самостоятельного анализа — без рекомендаций и призывов к действиям.
            </p>
            <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {FEATURES.map((item, i) => (
                <div
                  key={i}
                  className="card-glow hover-lift rounded-xl border border-slate-700/80 bg-slate-800/40 p-5 transition"
                >
                  <span className="text-2xl">{item.icon}</span>
                  <h3 className="mt-3 font-semibold text-white">
                    {item.title}
                  </h3>
                  <p className="mt-1.5 text-sm text-slate-400">{item.text}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Как это работает */}
        <section className="border-b border-slate-800/60 py-12 px-4 sm:py-14">
          <div className="mx-auto max-w-4xl">
            <h2 className="font-display text-2xl font-semibold text-white text-center sm:text-3xl">
              Как это работает
            </h2>
            <p className="mt-2 text-center text-slate-400 text-sm max-w-lg mx-auto">
              Три шага до полноценного доступа к аналитике
            </p>
            <div className="mt-10 grid gap-6 sm:grid-cols-3">
              {HOW_IT_WORKS.map((item) => (
                <div
                  key={item.step}
                  className="relative rounded-xl border border-slate-700/80 bg-slate-800/30 p-5 text-center transition hover:border-cyan-500/30"
                >
                  <span className="absolute -top-2 -right-2 flex h-7 w-7 items-center justify-center rounded-full bg-cyan-500/20 text-xs font-bold text-cyan-400">
                    {item.step}
                  </span>
                  <span className="text-2xl">{item.icon}</span>
                  <h3 className="mt-3 font-semibold text-white">{item.title}</h3>
                  <p className="mt-1.5 text-sm text-slate-400">{item.text}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Почему PingWin */}
        <section className="border-b border-slate-800/60 py-12 px-4 sm:py-14">
          <div className="mx-auto max-w-4xl">
            <h2 className="font-display text-2xl font-semibold text-white text-center sm:text-3xl">
              Почему PingWin
            </h2>
            <div className="mt-10 grid gap-4 sm:grid-cols-3">
              {WHY_US.map((item, i) => (
                <div
                  key={i}
                  className="rounded-xl border border-slate-700/80 bg-slate-800/30 p-5 transition hover:border-cyan-500/20"
                >
                  <h3 className="font-semibold text-white">{item.title}</h3>
                  <p className="mt-2 text-sm text-slate-400">{item.text}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Визуальный блок */}
        <section className="border-b border-slate-800/60 py-10 px-4">
          <div className="mx-auto max-w-4xl">
            <div className="relative overflow-hidden rounded-2xl border border-slate-700/80 bg-gradient-to-br from-slate-800/80 to-slate-900/80 p-8 sm:p-10">
              <div className="absolute inset-0 bg-[radial-gradient(circle_at_70%_50%,rgba(6,182,212,0.08),transparent_50%)]" />
              <div className="relative flex flex-col items-center gap-6 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex items-center gap-4">
                  <Image
                    src="/pingwin-logo.png"
                    alt="PingWin"
                    width={72}
                    height={72}
                    className="rounded-xl shadow-lg"
                  />
                  <div>
                    <p className="font-display text-xl font-semibold text-white">
                      Всё для анализа в одном месте
                    </p>
                    <p className="mt-0.5 text-sm text-slate-400">
                      Лайв, линия, статистика, уведомления — без лишнего шума
                    </p>
                  </div>
                </div>
                <Link
                  href="/register"
                  className="shrink-0 rounded-xl bg-cyan-500 px-5 py-2.5 text-sm font-medium text-white transition hover:bg-cyan-400"
                >
                  Попробовать
                </Link>
              </div>
            </div>
          </div>
        </section>
        {/* Вход и регистрация */}
        <section className="border-b border-slate-800/60 py-10 px-4">
          <div className="mx-auto max-w-2xl text-center">
            <h2 className="font-display text-xl font-semibold text-white">
              Вход и регистрация
            </h2>
            <p className="mt-2 text-slate-400 text-sm">
              Один аккаунт: почта или Telegram — полный доступ к аналитике.
            </p>
            <div className="mt-6 flex flex-wrap justify-center gap-4">
              <div className="flex items-center gap-3 rounded-xl border border-slate-700 bg-slate-800/50 px-5 py-3.5 transition hover:border-cyan-500/30">
                <span className="text-xl">📧</span>
                <div className="text-left">
                  <span className="font-medium text-white">Email</span>
                  <p className="text-slate-500 text-xs">Регистрация и вход</p>
                </div>
              </div>
              <div className="flex items-center gap-3 rounded-xl border border-slate-700 bg-slate-800/50 px-5 py-3.5 transition hover:border-cyan-500/30">
                <span className="text-xl">✈️</span>
                <div className="text-left">
                  <span className="font-medium text-white">Telegram</span>
                  <p className="text-slate-500 text-xs">Быстрый вход через бота</p>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* Важно */}
        <section className="border-b border-slate-800/60 py-8 px-4">
          <div className="mx-auto max-w-3xl">
            <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 px-6 py-5 text-center">
              <p className="text-sm text-amber-200/90">
                <strong>Важно:</strong> PingWin даёт только аналитику. Любые ставки — на ваш страх и риск. Обновление данных может идти с задержкой. Используя сервис, вы принимаете решения на свою ответственность; мы не несём ответственности за убытки. Подробнее — в{" "}
                <Link href="/terms" className="text-cyan-400 underline hover:no-underline">
                  правилах использования
                </Link>
                .
              </p>
            </div>
          </div>
        </section>

        {/* CTA */}
        <section className="py-12 px-4">
          <div className="mx-auto max-w-2xl rounded-2xl border border-slate-700/80 bg-gradient-to-b from-slate-800/60 to-slate-800/30 p-8 text-center card-glow">
            <h2 className="font-display text-2xl font-semibold text-white">
              Готовы смотреть аналитику?
            </h2>
            <p className="mt-2 text-slate-400 text-sm">
              Регистрация бесплатная. Лайв, линия, статистика по матчам — в одном месте.
            </p>
            <Link
              href="/register"
              className="hover-lift mt-6 inline-flex rounded-xl bg-cyan-500 px-8 py-3.5 font-medium text-white transition hover:bg-cyan-400"
            >
              Зарегистрироваться
            </Link>
          </div>
        </section>

        {/* Contact */}
        <section className="border-t border-slate-800/60 py-8 px-4">
          <div className="mx-auto max-w-xl text-center">
            <p className="text-slate-500 text-sm mb-3">Связь с нами</p>
            <div className="flex flex-wrap justify-center gap-6">
              <a
                href="https://t.me/PingwinBets"
                target="_blank"
                rel="noopener noreferrer"
                className="text-cyan-400 hover:text-cyan-300 font-medium transition"
              >
                @PingwinBets
              </a>
              <a
                href="mailto:info@pingwin.pro"
                className="text-cyan-400 hover:text-cyan-300 font-medium transition"
              >
                info@pingwin.pro
              </a>
            </div>
          </div>
        </section>

        <Footer />
      </main>
    </>
  );
}
