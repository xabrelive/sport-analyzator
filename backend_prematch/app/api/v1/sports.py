"""Public list of sports for subscription selection."""
from fastapi import APIRouter

router = APIRouter()

# Виды спорта, доступные для подписки «один вид».
AVAILABLE_SPORTS = [
    {"id": "table_tennis", "name": "Настольный теннис"},
    # Добавлять по мере подключения источников
]


@router.get("")
def list_sports():
    """Список видов спорта для выбора при подписке «один вид»."""
    return AVAILABLE_SPORTS
