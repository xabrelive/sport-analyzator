"""Application models."""
from app.models.user import User
from app.models.verification_code import VerificationCode
from app.models.table_tennis_line_event import TableTennisLineEvent
from app.models.table_tennis_player import TableTennisPlayer
from app.models.table_tennis_league import TableTennisLeague
from app.models.table_tennis_league_rule import TableTennisLeagueRule
from app.models.table_tennis_model_run import TableTennisModelRun
from app.models.table_tennis_player_daily_feature import TableTennisPlayerDailyFeature
from app.models.table_tennis_match_feature import TableTennisMatchFeature
from app.models.table_tennis_forecast_v2 import TableTennisForecastV2
from app.models.table_tennis_forecast_explanation import TableTennisForecastExplanation
from app.models.user_forecast_notification import UserForecastNotification
from app.models.telegram_channel_notification import TelegramChannelNotification
from app.models.telegram_channel_marker import TelegramChannelMarker
from app.models.billing_product import BillingProduct
from app.models.payment_method import PaymentMethod
from app.models.user_subscription import UserSubscription
from app.models.invoice import Invoice
from app.models.app_setting import AppSetting

__all__ = [
    "User",
    "VerificationCode",
    "TableTennisLineEvent",
    "TableTennisPlayer",
    "TableTennisLeague",
    "TableTennisLeagueRule",
    "TableTennisModelRun",
    "TableTennisPlayerDailyFeature",
    "TableTennisMatchFeature",
    "TableTennisForecastV2",
    "TableTennisForecastExplanation",
    "UserForecastNotification",
    "TelegramChannelNotification",
    "TelegramChannelMarker",
    "BillingProduct",
    "PaymentMethod",
    "UserSubscription",
    "Invoice",
    "AppSetting",
]
