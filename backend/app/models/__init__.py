"""Application models."""
from app.models.user import User
from app.models.verification_code import VerificationCode
from app.models.table_tennis_line_event import TableTennisLineEvent
from app.models.table_tennis_player import TableTennisPlayer
from app.models.table_tennis_league import TableTennisLeague
from app.models.table_tennis_league_rule import TableTennisLeagueRule
from app.models.table_tennis_forecast import TableTennisForecast

__all__ = [
    "User",
    "VerificationCode",
    "TableTennisLineEvent",
    "TableTennisPlayer",
    "TableTennisLeague",
    "TableTennisLeagueRule",
    "TableTennisForecast",
]
