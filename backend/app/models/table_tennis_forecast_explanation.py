"""Feature-level explanation rows for forecast V2."""
from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TableTennisForecastExplanation(Base):
    __tablename__ = "table_tennis_forecast_explanations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    forecast_v2_id: Mapped[int] = mapped_column(
        ForeignKey("table_tennis_forecasts_v2.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    factor_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    factor_label: Mapped[str] = mapped_column(String(255), nullable=False)
    factor_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contribution: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    direction: Mapped[str] = mapped_column(String(16), nullable=False, default="neutral")
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
