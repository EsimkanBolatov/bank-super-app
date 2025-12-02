from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.db.database import get_db
from app.db.models import User, Account, Transaction
from app.schemas.transfer import TransferRequest
from app.dependencies import get_current_user

router = APIRouter(prefix="/transfers", tags=["Transfers"])

@router.post("/p2p")
async def make_transfer(
        transfer: TransferRequest,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    # 1. Находим счет ОТПРАВИТЕЛЯ
    sender_account = None
    
    if transfer.from_account_id:
        # Если фронт прислал ID карты, ищем конкретную
        q = select(Account).where(Account.id == transfer.from_account_id, Account.user_id == current_user.id)
        res = await db.execute(q)
        sender_account = res.scalar_one_or_none()
    else:
        # Иначе берем первую попавшуюся (фоллбэк)
        query_sender = select(Account).where(
            Account.user_id == current_user.id,
            Account.is_blocked == False
        )
        result_sender = await db.execute(query_sender)
        sender_account = result_sender.scalars().first()

    if not sender_account:
        raise HTTPException(status_code=400, detail="Нет счета для списания или он не найден")

    if sender_account.is_blocked:
        raise HTTPException(status_code=403, detail="Карта заблокирована. Перевод невозможен.")  

    if sender_account.balance < transfer.amount:
        raise HTTPException(status_code=400, detail="Недостаточно средств")

    # 2. Находим счет ПОЛУЧАТЕЛЯ
    recipient_account = None

    if transfer.to_card:
        # Чистим номер карты от пробелов
        clean_card = transfer.to_card.replace(" ", "")
        query_recipient = select(Account).where(Account.card_number == clean_card)
        res = await db.execute(query_recipient)
        recipient_account = res.scalar_one_or_none()

    elif transfer.to_phone:
        # Чистим телефон
        clean_phone = transfer.to_phone.replace(" ", "").replace("(", "").replace(")", "").replace("-", "")
        if clean_phone.startswith("+7"): clean_phone = "8" + clean_phone[2:]
        elif clean_phone.startswith("7"): clean_phone = "8" + clean_phone[1:]

        query_user = select(User).where(User.phone == clean_phone).options(selectinload(User.accounts))
        res = await db.execute(query_user)
        recipient_user = res.scalar_one_or_none()

        if recipient_user and recipient_user.accounts:
            recipient_account = recipient_user.accounts[0]

    # Если получатель не найден внутри банка, но это перевод по карте - считаем это внешним переводом
    # (В реальной жизни тут интеграция с Visa/Mastercard, здесь - эмуляция)
    if not recipient_account and transfer.to_card:
        # ЭМУЛЯЦИЯ ВНЕШНЕГО ПЕРЕВОДА
        sender_account.balance -= transfer.amount
        
        new_transaction = Transaction(
            from_account_id=sender_account.id,
            to_account_id=None, # Внешний
            amount=transfer.amount,
            category=f"Перевод на карту другого банка: {transfer.to_card[-4:]}"
        )
        db.add(new_transaction)
        await db.commit()
        return {"status": "success", "message": "Перевод в другой банк отправлен"}

    if not recipient_account:
        raise HTTPException(status_code=404, detail="Получатель не найден в Belly Bank")

    if sender_account.id == recipient_account.id:
        raise HTTPException(status_code=400, detail="Нельзя переводить самому себе на ту же карту")

    # 3. ВНУТРЕННИЙ ПЕРЕВОД (ACID)
    try:
        sender_account.balance -= transfer.amount
        recipient_account.balance += transfer.amount

        new_transaction = Transaction(
            from_account_id=sender_account.id,
            to_account_id=recipient_account.id,
            amount=transfer.amount,
            category="Transfer P2P"
        )
        db.add(new_transaction)

        await db.commit()

        return {"status": "success", "message": "Перевод выполнен", "transaction_id": new_transaction.id}

    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Ошибка при переводе")