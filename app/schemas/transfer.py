from pydantic import BaseModel, Field
from decimal import Decimal

class TransferRequest(BaseModel):
    amount: Decimal = Field(..., gt=0, description="Сумма перевода больше 0")
    to_card: str | None = None
    to_phone: str | None = None
    from_account_id: int | None = None

    # Валидация: должен быть указан ЛИБО номер карты, ЛИБО телефон