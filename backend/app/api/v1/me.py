"""Current user: access summary and subscriptions. Requires JWT."""
import logging
from datetime import date, datetime, time, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v1.auth import get_current_user, create_verify_email_token
from app.config import settings
from app.services.email import send_verification_email
from app.db.session import get_async_session
from app.models import User, UserSubscription, Match, MatchRecommendation
from app.models.match_result import MatchResult
from app.models.user_signal_delivery import UserSignalDelivery
from app.models.user_subscription import AccessType, SubscriptionScope
from app.services.signal_delivery_service import get_recommendation_outcome
from app.models.invoice import Invoice
from app.models.subscription_grant_log import SubscriptionGrantLog
from app.schemas.subscription import (
    AccessItem,
    AccessSummary,
    GrantSubscriptionBody,
    SubscriptionOut,
)
from app.services.telegram_channel_service import invite_user_to_paid_channel_async
from app.services.telegram_link_service import create_link_code, create_link_token

router = APIRouter()
logger = logging.getLogger(__name__)


def _today() -> date:
    return datetime.now(timezone.utc).date()


class MyProfileOut(BaseModel):
    id: str
    email: str
    email_verified: bool = False
    telegram_linked: bool = False
    telegram_username: str | None = None
    signal_via_telegram: bool = True
    signal_via_email: bool = True
    is_admin: bool = False
    trial_until: str | None = None


class PatchProfileBody(BaseModel):
    signal_via_telegram: bool | None = None
    signal_via_email: bool | None = None


class RequestVerifyEmailBody(BaseModel):
    email: EmailStr


@router.get("/access", response_model=AccessSummary)
async def get_my_access(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Сводка: есть ли доступ к полной аналитике (ТГ) и к сигналам, до какой даты."""
    q = (
        select(UserSubscription)
        .where(
            UserSubscription.user_id == user.id,
            UserSubscription.valid_until >= _today(),
        )
    )
    result = await session.execute(q)
    subs = list(result.scalars().all())

    def pick_best(subs_list: list[UserSubscription], access_type: str) -> AccessItem:
        filtered = [s for s in subs_list if s.access_type == access_type]
        if not filtered:
            return AccessItem(has=False)
        best = max(filtered, key=lambda s: s.valid_until)
        return AccessItem(
            has=True,
            valid_until=best.valid_until,
            scope=best.scope,
            sport_key=best.sport_key,
            connected_at=best.connected_at,
        )

    return AccessSummary(
        tg_analytics=pick_best(subs, AccessType.TG_ANALYTICS.value),
        signals=pick_best(subs, AccessType.SIGNALS.value),
    )


@router.get("/profile", response_model=MyProfileOut)
async def get_my_profile(user: User = Depends(get_current_user)):
    """Текущий пользователь: профиль для личного кабинета (каналы связи, куда отправлять сигналы)."""
    return MyProfileOut(
        id=str(user.id),
        email=user.email,
        email_verified=user.email_verified,
        telegram_linked=user.telegram_id is not None,
        telegram_username=user.telegram_username,
        signal_via_telegram=user.signal_via_telegram,
        signal_via_email=user.signal_via_email,
        is_admin=getattr(user, "is_admin", False),
        trial_until=user.trial_until.isoformat() if getattr(user, "trial_until", None) else None,
    )


@router.patch("/profile", response_model=MyProfileOut)
async def patch_my_profile(
    body: PatchProfileBody,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Обновить настройки профиля (куда отправлять сигналы: Telegram, почта)."""
    if body.signal_via_telegram is not None:
        user.signal_via_telegram = body.signal_via_telegram
    if body.signal_via_email is not None:
        user.signal_via_email = body.signal_via_email
    await session.commit()
    await session.refresh(user)
    return MyProfileOut(
        id=str(user.id),
        email=user.email,
        email_verified=user.email_verified,
        telegram_linked=user.telegram_id is not None,
        telegram_username=user.telegram_username,
        signal_via_telegram=user.signal_via_telegram,
        signal_via_email=user.signal_via_email,
        is_admin=getattr(user, "is_admin", False),
        trial_until=user.trial_until.isoformat() if getattr(user, "trial_until", None) else None,
    )


class LinkTelegramRequestOut(BaseModel):
    link: str
    code: str  # 6 цифр — пользователь пишет этот код боту для привязки
    expires_in_seconds: int


@router.post("/request-verify-email", response_model=dict)
async def request_verify_email(
    body: RequestVerifyEmailBody,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Запросить письмо подтверждения для привязки/смены почты. Для аккаунтов с placeholder-email или для смены не подтверждённой почты."""
    r = await session.execute(select(User).where(User.email == body.email))
    other_user = r.scalar_one_or_none()
    if other_user is not None and other_user.id != user.id:
        raise HTTPException(status_code=400, detail="Этот email уже используется другим аккаунтом.")
    user.email = body.email
    user.email_verified = False
    await session.commit()
    await session.refresh(user)
    token = create_verify_email_token(str(user.id))
    base = (settings.frontend_public_url or settings.frontend_url or "").rstrip("/")
    verify_link = f"{base}/verify-email?token={token}"
    try:
        send_verification_email(body.email, verify_link)
    except Exception as e:
        logger.warning("Could not send verification email: %s", e)
    return {"message": "check_email", "detail": "Перейдите по ссылке из письма для подтверждения почты."}


@router.post("/link-telegram-request", response_model=LinkTelegramRequestOut)
async def link_telegram_request(user: User = Depends(get_current_user)):
    """Выдать код и ссылку для привязки Telegram. Код пользователь пишет боту; ссылка — альтернатива. Действует 15 минут."""
    if user.telegram_id is not None:
        raise HTTPException(status_code=400, detail="Telegram уже привязан.")
    token = await create_link_token(user.id)
    code = await create_link_code(user.id)
    bot_username = (settings.telegram_bot_username or "").strip().lstrip("@") or "pingwinbetsbot"
    link = f"https://t.me/{bot_username}?start=link_{token}"
    return LinkTelegramRequestOut(link=link, code=code, expires_in_seconds=900)


@router.post("/unlink-telegram", response_model=MyProfileOut)
async def unlink_telegram(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Отвязать Telegram от аккаунта. Уведомления в бота перестанут приходить; войти по почте по-прежнему можно."""
    if user.telegram_id is None:
        raise HTTPException(status_code=400, detail="Telegram не привязан.")
    user.telegram_id = None
    user.telegram_username = None
    await session.commit()
    await session.refresh(user)
    return MyProfileOut(
        id=str(user.id),
        email=user.email,
        email_verified=user.email_verified,
        telegram_linked=False,
        telegram_username=None,
        signal_via_telegram=user.signal_via_telegram,
        signal_via_email=user.signal_via_email,
        is_admin=getattr(user, "is_admin", False),
        trial_until=user.trial_until.isoformat() if getattr(user, "trial_until", None) else None,
    )


@router.get("/subscriptions", response_model=list[SubscriptionOut])
async def list_my_subscriptions(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Список активных подписок (valid_until >= сегодня), от старых к новым по дате окончания."""
    q = (
        select(UserSubscription)
        .where(
            UserSubscription.user_id == user.id,
            UserSubscription.valid_until >= _today(),
        )
        .order_by(UserSubscription.valid_until.asc(), UserSubscription.connected_at.asc())
    )
    result = await session.execute(q)
    return list(result.scalars().all())


@router.post("/subscriptions", response_model=SubscriptionOut)
async def grant_my_subscription(
    body: GrantSubscriptionBody,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """
    Выдать себе подписку. В проде отключено: подписка только через оплату (биллинг).
    Для теста задайте ENABLE_DEMO_GRANT=true.
    """
    if not getattr(settings, "enable_demo_grant", False):
        raise HTTPException(
            status_code=400,
            detail="Подписка оформляется только через оплату. Нажмите «Оплатить» и выберите способ оплаты.",
        )
    if body.user_id is not None:
        raise HTTPException(status_code=400, detail="user_id не допускается для текущего пользователя")
    if body.scope == SubscriptionScope.ONE_SPORT.value and not body.sport_key:
        raise HTTPException(status_code=400, detail="Укажите sport_key для доступа «один вид спорта»")

    sub = UserSubscription(
        user_id=user.id,
        access_type=body.access_type,
        scope=body.scope,
        sport_key=body.sport_key,
        valid_until=body.valid_until,
    )
    session.add(sub)
    await session.commit()
    await session.refresh(sub)
    if (
        body.access_type == AccessType.SIGNALS.value
        and user.telegram_id
        and (settings.telegram_signals_paid_chat_id or "").strip()
    ):
        try:
            await invite_user_to_paid_channel_async(user.telegram_id)
        except Exception as e:
            logger.warning("Invite to paid channel failed: %s", e)
    return sub


@router.get("/topup-history")
async def get_my_topup_history(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """История пополнений: счета (оплаты) и выдачи подписок через админку."""
    invs = (await session.execute(
        select(Invoice).where(Invoice.user_id == user.id).order_by(Invoice.created_at.desc()).limit(50)
    )).scalars().all()
    grants = (await session.execute(
        select(SubscriptionGrantLog).where(SubscriptionGrantLog.user_id == user.id).order_by(SubscriptionGrantLog.created_at.desc()).limit(50)
    )).scalars().all()
    return {
        "invoices": [
            {"id": str(i.id), "amount": float(i.amount), "currency": i.currency, "status": i.status, "created_at": i.created_at.isoformat() if i.created_at else None, "paid_at": i.paid_at.isoformat() if i.paid_at else None}
            for i in invs
        ],
        "subscription_grants": [
            {"id": str(g.id), "access_type": g.access_type, "scope": g.scope, "sport_key": g.sport_key, "valid_until": g.valid_until.isoformat(), "comment": g.comment, "created_at": g.created_at.isoformat() if g.created_at else None}
            for g in grants
        ],
    }


class MySignalItem(BaseModel):
    match_id: str
    league_name: str = ""
    start_time: str = ""
    home_name: str = ""
    away_name: str = ""
    recommendation_text: str = ""
    outcome: str = ""
    sent_at: str = ""
    sent_via: str = ""


class MySignalsResponse(BaseModel):
    total: int = 0
    won: int = 0
    lost: int = 0
    pending: int = 0
    items: list[MySignalItem] = []
    bank_profit_rub: float = 0.0
    avg_odds: float | None = None


@router.get("/signals", response_model=MySignalsResponse)
async def get_my_signals(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    days: int = Query(30, ge=1, le=365),
):
    """Сигналы, отправленные пользователю в личку (TG/email): что зашло, что нет."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    q = (
        select(UserSignalDelivery)
        .where(
            UserSignalDelivery.user_id == user.id,
            UserSignalDelivery.sent_at >= since,
        )
        .order_by(UserSignalDelivery.sent_at.desc())
    )
    deliveries = (await session.execute(q)).scalars().all()
    rec_ids = list({d.match_recommendation_id for d in deliveries})
    if not rec_ids:
        return MySignalsResponse()

    recs_q = (
        select(MatchRecommendation)
        .where(MatchRecommendation.id.in_(rec_ids))
        .options(
            selectinload(MatchRecommendation.match).selectinload(Match.league),
            selectinload(MatchRecommendation.match).selectinload(Match.home_player),
            selectinload(MatchRecommendation.match).selectinload(Match.away_player),
            selectinload(MatchRecommendation.match).selectinload(Match.result),
            selectinload(MatchRecommendation.match).selectinload(Match.scores),
        )
    )
    recs = (await session.execute(recs_q)).scalars().all()
    rec_by_id = {r.id: r for r in recs}

    by_rec: dict = {}
    for d in deliveries:
        if d.match_recommendation_id not in by_rec:
            by_rec[d.match_recommendation_id] = {"sent_at": d.sent_at.isoformat() if d.sent_at else "", "sent_via": d.sent_via}

    total = won = lost = pending = 0
    bank_profit = 0.0
    odds_sum = 0.0
    odds_count = 0
    items: list[MySignalItem] = []
    for rec_id, rec in rec_by_id.items():
        rec_obj = rec
        match = rec_obj.match
        if not match:
            continue
        outcome = get_recommendation_outcome(rec_obj, match)
        odds = float(rec_obj.odds_at_recommendation) if rec_obj.odds_at_recommendation is not None else None
        if outcome == "won":
            won += 1
            if odds is not None:
                bank_profit += 100.0 * (odds - 1.0)
        elif outcome == "lost":
            lost += 1
            bank_profit -= 100.0
        else:
            pending += 1
        total += 1
        if odds is not None:
            odds_sum += odds
            odds_count += 1
        info = by_rec.get(rec_id, {})
        items.append(
            MySignalItem(
                match_id=str(match.id),
                league_name=match.league.name if match.league else "",
                start_time=match.start_time.isoformat() if match.start_time else "",
                home_name=match.home_player.name if match.home_player else "?",
                away_name=match.away_player.name if match.away_player else "?",
                recommendation_text=rec_obj.recommendation_text or "",
                outcome=outcome,
                sent_at=info.get("sent_at", ""),
                sent_via=info.get("sent_via", ""),
            )
        )
    items.sort(key=lambda x: x.start_time or "", reverse=True)
    avg_odds = (odds_sum / odds_count) if odds_count else None
    return MySignalsResponse(
        total=total,
        won=won,
        lost=lost,
        pending=pending,
        items=items,
        bank_profit_rub=round(bank_profit, 0),
        avg_odds=round(avg_odds, 2) if avg_odds is not None else None,
    )
