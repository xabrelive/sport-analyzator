"""
Очистка БД (кроме users) и заполнение тестовыми данными:
- 300–1000 матчей в линии (scheduled), лайве (live со счётом по сетам), в результатах (finished с result).
- Разные лиги, у части игроков много матчей в разные дни.
- Сигналы (free/paid, won/lost) для блоков на главной.
- Тестовый пользователь test@example.com / test123 (email_verified) для входа по почте.

Перед первым запуском: alembic upgrade head
Запуск: uv run python scripts/seed_test_data.py
В Docker: docker compose exec backend uv run python scripts/seed_test_data.py
"""
from __future__ import annotations

import os
import random
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

os.environ.setdefault("DATABASE_URL", "postgresql://sport:sport@localhost:11002/sport_analyzator")

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker
import bcrypt

from app.config import settings
from app.models import (
    League,
    Match,
    MatchResult,
    MatchScore,
    MatchStatus,
    OddsSnapshot,
    Player,
    Signal,
    SignalChannel,
    SignalOutcome,
    User,
)

db_url = settings.database_url
if "+" in (db_url.split("://")[1] if "://" in db_url else ""):
    db_url = db_url.replace("postgresql+asyncpg://", "postgresql://", 1)
engine = create_engine(db_url, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, autocommit=False, autoflush=False)


def hash_password(password: str) -> str:
    """Bcrypt hash, совместимый с passlib в auth (оба дают $2b$...)."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


TEST_USER_EMAIL = "test@example.com"
TEST_USER_PASSWORD = "test123"

N_SCHEDULED = random.randint(300, 1000)
N_LIVE = random.randint(300, 1000)
N_FINISHED = random.randint(300, 1000)
N_LEAGUES = 24
N_PLAYERS = 600
N_STAR_PLAYERS = 80  # эти игроки участвуют в матчах чаще — у каждого много игр в разные дни

LEAGUE_NAMES = [
    "WTT Champions", "ITTF World Tour", "Europe Top 16", "Chinese Super League",
    "German Bundesliga", "Japanese T-League", "Russian Premier League",
    "French Pro A", "Polish Superliga", "Spanish Liga", "Setka Cup",
    "Czech Extraliga", "Italian Serie A", "Austrian Bundesliga", "Swedish Elitserien",
    "Portuguese Liga", "Greek A1", "Ukrainian Superliga", "Croatian League",
    "English Premier League", "Dutch Eredivisie", "Belgian League",
    "Champions League", "Europa League",
]
COUNTRIES = ["CHN", "JPN", "GER", "FRA", "KOR", "RUS", "POL", "ESP", "SWE", "AUT", "CZE", "ITA", "UKR"]
FIRST_NAMES = [
    "Ma Long", "Fan Zhendong", "Xu Xin", "Lin Gaoyuan", "Wang Chuqin",
    "Tomokazu Harimoto", "Hugo Calderano", "Timo Boll", "Dimitrij Ovtcharov",
    "Chen Meng", "Sun Yingsha", "Mima Ito", "Ding Ning", "Wang Manyu",
    "Kasumi Ishikawa", "Bernadette Szocs", "Petrissa Solja", "Han Ying",
]
LAST_NAMES = ["Zhang", "Wang", "Liu", "Chen", "Li", "Yang", "Yamada", "Tanaka", "Schmidt", "Müller", "Kim", "Ivanov", "Kovács"]
PRIMARY_BOOKMAKER = "Pinnacle"


def random_player_name() -> str:
    return f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"


def truncate_all(session: Session) -> None:
    """Очистка таблиц (без users). Порядок из-за FK."""
    session.execute(text("TRUNCATE TABLE signals RESTART IDENTITY CASCADE"))
    session.execute(text("TRUNCATE TABLE match_results RESTART IDENTITY CASCADE"))
    session.execute(text("TRUNCATE TABLE odds_snapshots RESTART IDENTITY CASCADE"))
    session.execute(text("TRUNCATE TABLE match_scores RESTART IDENTITY CASCADE"))
    session.execute(text("TRUNCATE TABLE matches RESTART IDENTITY CASCADE"))
    session.execute(text("TRUNCATE TABLE leagues RESTART IDENTITY CASCADE"))
    session.execute(text("TRUNCATE TABLE players RESTART IDENTITY CASCADE"))
    session.commit()


def add_odds_for_match(session: Session, match_id: uuid.UUID, bookmaker: str = PRIMARY_BOOKMAKER) -> None:
    o1 = round(random.uniform(1.3, 2.8), 2)
    o2 = round(random.uniform(1.3, 2.8), 2)
    session.add(OddsSnapshot(match_id=match_id, bookmaker=bookmaker, market="winner", selection="home", odds=Decimal(str(o1))))
    session.add(OddsSnapshot(match_id=match_id, bookmaker=bookmaker, market="winner", selection="away", odds=Decimal(str(o2))))
    s1 = round(random.uniform(1.4, 2.6), 2)
    s2 = round(random.uniform(1.4, 2.6), 2)
    session.add(OddsSnapshot(match_id=match_id, bookmaker=bookmaker, market="set_winner", selection="set_1_home", odds=Decimal(str(s1))))
    session.add(OddsSnapshot(match_id=match_id, bookmaker=bookmaker, market="set_winner", selection="set_1_away", odds=Decimal(str(s2))))
    over = round(random.uniform(1.5, 2.2), 2)
    under = round(random.uniform(1.6, 2.3), 2)
    session.add(OddsSnapshot(match_id=match_id, bookmaker=bookmaker, market="total", selection="over_5.5", odds=Decimal(str(over))))
    session.add(OddsSnapshot(match_id=match_id, bookmaker=bookmaker, market="total", selection="under_5.5", odds=Decimal(str(under))))
    session.add(OddsSnapshot(match_id=match_id, bookmaker=bookmaker, market="handicap", selection="home_-1.5", odds=Decimal(str(round(random.uniform(1.7, 2.4), 2)))))
    session.add(OddsSnapshot(match_id=match_id, bookmaker=bookmaker, market="handicap", selection="away_+1.5", odds=Decimal(str(round(random.uniform(1.6, 2.2), 2)))))


def pick_two_players(players: list[Player], star_players: list[Player]) -> tuple[Player, Player]:
    """С вероятностью 0.5 хотя бы один из игроков — из «звёзд», чтобы у них было много матчей в разные дни."""
    if random.random() < 0.5 and star_players:
        home = random.choice(star_players)
        away = random.choice(players)
        while away.id == home.id:
            away = random.choice(players)
        return home, away
    home = random.choice(players)
    away = random.choice(players)
    while away.id == home.id:
        away = random.choice(players)
    return home, away


def seed(session: Session) -> None:
    now = datetime.now(timezone.utc)

    print("Truncating (signals, match_results, odds_snapshots, match_scores, matches, leagues, players)...")
    truncate_all(session)

    # Тестовый пользователь для входа по почте (пароль: test123)
    r = session.execute(select(User).where(User.email == TEST_USER_EMAIL))
    if r.scalar_one_or_none() is None:
        print("Creating test user test@example.com / test123 (email verified)...")
        session.add(User(
            email=TEST_USER_EMAIL,
            hashed_password=hash_password(TEST_USER_PASSWORD),
            email_verified=True,
        ))
        session.flush()
    else:
        print("Test user test@example.com already exists.")

    print("Creating leagues...")
    leagues = []
    for i in range(N_LEAGUES):
        name = LEAGUE_NAMES[i % len(LEAGUE_NAMES)]
        if i >= len(LEAGUE_NAMES):
            name = f"{name} {i}"
        league = League(
            id=uuid.uuid4(),
            name=name,
            country=random.choice(COUNTRIES) if random.random() > 0.2 else None,
            provider_league_id=f"seed_league_{i}",
            provider="seed",
        )
        session.add(league)
        leagues.append(league)
    session.flush()

    print("Creating players...")
    players = []
    for i in range(N_PLAYERS):
        p = Player(
            id=uuid.uuid4(),
            name=random_player_name() + (f"_{i}" if i >= len(FIRST_NAMES) * len(LAST_NAMES) else ""),
            provider_player_id=f"seed_player_{i}",
            provider="seed",
        )
        session.add(p)
        players.append(p)
    session.flush()
    star_players = players[:N_STAR_PLAYERS]

    def add_match(
        status: str,
        start_time: datetime,
        with_scores: bool = False,
        with_result: bool = False,
    ) -> Match:
        home, away = pick_two_players(players, star_players)
        m = Match(
            id=uuid.uuid4(),
            provider_match_id=f"seed_{status}_{uuid.uuid4().hex[:12]}",
            provider="seed",
            league_id=random.choice(leagues).id,
            home_player_id=home.id,
            away_player_id=away.id,
            start_time=start_time,
            status=status,
            sets_to_win=2,
            points_per_set=11,
            win_by=2,
            is_doubles=False,
        )
        session.add(m)
        session.flush()
        if with_scores:
            n_sets = random.randint(2, 5)
            for set_num in range(1, n_sets + 1):
                h = random.randint(0, 11)
                a = random.randint(0, 11)
                if h == a:
                    h, a = (11, 9) if random.random() > 0.5 else (9, 11)
                session.add(MatchScore(match_id=m.id, set_number=set_num, home_score=h, away_score=a))
            session.flush()
        if with_result:
            scores_list = session.execute(
                select(MatchScore).where(MatchScore.match_id == m.id).order_by(MatchScore.set_number)
            ).scalars().all()
            if scores_list:
                home_sets = sum(1 for s in scores_list if s.home_score > s.away_score)
                away_sets = len(scores_list) - home_sets
                winner_id = home.id if home_sets > away_sets else away.id
                score_str = " ".join(f"{s.home_score}:{s.away_score}" for s in scores_list)
                session.add(MatchResult(match_id=m.id, final_score=score_str, winner_id=winner_id, finished_at=now))
        add_odds_for_match(session, m.id)
        session.flush()
        return m

    print(f"Creating {N_SCHEDULED} scheduled (line)...")
    for i in range(N_SCHEDULED):
        start = now + timedelta(days=random.randint(1, 60), hours=random.randint(0, 23), minutes=random.randint(0, 59))
        add_match(MatchStatus.SCHEDULED.value, start)
        if (i + 1) % 200 == 0:
            session.commit()
            session.flush()
            print(f"  {i + 1}/{N_SCHEDULED}")

    print(f"Creating {N_LIVE} live (with set scores)...")
    for i in range(N_LIVE):
        start = now - timedelta(hours=random.randint(0, 2), minutes=random.randint(0, 59))
        add_match(MatchStatus.LIVE.value, start, with_scores=True)
        if (i + 1) % 200 == 0:
            session.commit()
            session.flush()
            print(f"  {i + 1}/{N_LIVE}")

    print(f"Creating {N_FINISHED} finished (with scores + result)...")
    for i in range(N_FINISHED):
        start = now - timedelta(days=random.randint(1, 90), hours=random.randint(0, 23), minutes=random.randint(0, 59))
        add_match(MatchStatus.FINISHED.value, start, with_scores=True, with_result=True)
        if (i + 1) % 200 == 0:
            session.commit()
            session.flush()
            print(f"  {i + 1}/{N_FINISHED}")

    session.commit()
    session.flush()

    # Сигналы для главной: бесплатный канал и платная подписка, угадано/не угадано за разные периоды
    print("Creating signals (free channel + paid subscription, won/lost)...")
    r = session.execute(select(Match).where(Match.status == MatchStatus.FINISHED.value).limit(800))
    for_match_signals = list(r.scalars().all())
    r_live = session.execute(select(Match).where(Match.status == MatchStatus.LIVE.value).limit(200))
    for_match_signals += list(r_live.scalars().all())
    random.shuffle(for_match_signals)
    outcomes = [SignalOutcome.WON, SignalOutcome.LOST, SignalOutcome.PENDING]
    channels = [SignalChannel.FREE, SignalChannel.PAID]
    n_signals = 0
    for m in for_match_signals[:600]:
        created = now - timedelta(days=random.randint(0, 35), hours=random.randint(0, 23))
        ch = random.choice(channels)
        out = random.choice(outcomes)
        session.add(Signal(
            match_id=m.id,
            market_type="winner",
            selection="home" if random.random() > 0.5 else "away",
            outcome=out.value,
            channel=ch,
            created_at=created,
        ))
        n_signals += 1
        if random.random() < 0.4:
            session.add(Signal(
                match_id=m.id,
                market_type="set_winner",
                selection="set_1_home",
                outcome=random.choice(outcomes).value,
                channel=random.choice(channels),
                created_at=created - timedelta(hours=1),
            ))
            n_signals += 1
        if n_signals % 300 == 0 and n_signals:
            session.commit()
            session.flush()
    session.commit()

    print("Done.")
    print(f"  Leagues: {N_LEAGUES}, Players: {N_PLAYERS} (stars: {N_STAR_PLAYERS})")
    print(f"  Scheduled (line): {N_SCHEDULED}, Live: {N_LIVE}, Finished: {N_FINISHED}")
    print(f"  Signals: {n_signals}")


def main() -> None:
    with SessionLocal() as session:
        seed(session)


if __name__ == "__main__":
    main()
