from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from pydantic import BaseModel

from app.db.database import get_db
from app.db.models import User, Account, Transaction, Favorite
from app.schemas.transfer import TransferRequest
from app.dependencies import get_current_user

router = APIRouter(prefix="/transfers", tags=["Transfers & Favorites"])

# --- СХЕМЫ ИЗБРАННОГО ---
class FavoriteCreate(BaseModel):
    name: str
    value: str
    type: str

@router.get("/favorites")
async def get_favorites(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    res = await db.execute(select(Favorite).where(Favorite.user_id == current_user.id))
    return [{"id": f.id, "name": f.name, "value": f.value, "type": f.type, "color": [f.color_start, f.color_end]} for f in res.scalars().all()]

@router.post("/favorites")
async def add_favorite(fav: FavoriteCreate, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    new_fav = Favorite(user_id=current_user.id, name=fav.name, value=fav.value, type=fav.type)
    db.add(new_fav)
    await db.commit()
    return {"status": "ok"}

@router.delete("/favorites/{fav_id}")
async def delete_favorite(fav_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    res = await db.execute(select(Favorite).where(Favorite.id == fav_id, Favorite.user_id == current_user.id))
    if fav := res.scalar_one_or_none():
        await db.delete(fav)
        await db.commit()
    return {"status": "ok"}

# --- ГЛАВНАЯ ЛОГИКА ПЕРЕВОДА ---
@router.post("/p2p")
async def make_transfer(
        transfer: TransferRequest,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    # 1. ОПРЕДЕЛЯЕМ ОТПРАВИТЕЛЯ
    # Если фронт прислал ID карты - используем её. Если нет - ищем первую попавшуюся.
    sender_account = None
    if transfer.from_account_id:
        res = await db.execute(select(Account).where(Account.id == transfer.from_account_id, Account.user_id == current_user.id))
        sender_account = res.scalar_one_or_none()
    
    if not sender_account:
        # Фоллбэк (если вдруг ID не пришел)
        res = await db.execute(select(Account).where(Account.user_id == current_user.id, Account.is_blocked == False))
        sender_account = res.scalars().first()

    if not sender_account:
        raise HTTPException(status_code=400, detail="У вас нет активных счетов для списания")
    
    if sender_account.is_blocked:
         raise HTTPException(status_code=403, detail="Карта списания заблокирована")

    if sender_account.balance < transfer.amount:
        raise HTTPException(status_code=400, detail="Недостаточно средств")

    # 2. ОПРЕДЕЛЯЕМ ПОЛУЧАТЕЛЯ
    recipient_account = None
    
    # Чистим данные
    clean_phone = None
    if transfer.to_phone:
        # Убираем всё лишнее, оставляем цифры. Если начинается с 7 или 8, меняем на 8 для поиска в БД (т.к. при регистрации мы сохраняли как 8...)
        # В идеале в БД хранить все как 7..., но раз начали с 8, продолжим.
        clean_phone = transfer.to_phone.replace(" ", "").replace("+", "").replace("-", "").replace("(", "").replace(")", "")
        if clean_phone.startswith("7"): clean_phone = "8" + clean_phone[1:]
        
    clean_card = transfer.to_card.replace(" ", "") if transfer.to_card else None

    # А) Перевод по телефону (Внутренний)
    if clean_phone:
        res = await db.execute(select(User).where(User.phone == clean_phone).options(selectinload(User.accounts)))
        recipient_user = res.scalar_one_or_none()
        
        if not recipient_user:
            # ВАЖНО: Если по телефону не нашли — это ошибка, так как по телефону только своим
            raise HTTPException(status_code=404, detail="Клиент с таким номером не найден в банке")
            
        if recipient_user.accounts:
            recipient_account = recipient_user.accounts[0]
        else:
            raise HTTPException(status_code=400, detail="У получателя нет открытых счетов")

    # Б) Перевод по карте (Внутренний или Внешний)
    elif clean_card:
        res = await db.execute(select(Account).where(Account.card_number == clean_card))
        recipient_account = res.scalar_one_or_none()

    # 3. ПРОВЕРКИ И ТРАНЗАКЦИЯ
    
    # Если это перевод самому себе на ту же карту
    if recipient_account and sender_account.id == recipient_account.id:
        raise HTTPException(status_code=400, detail="Нельзя переводить на ту же карту. Выберите другую.")

    try:
        # Списание
        sender_account.balance -= transfer.amount
        
        if recipient_account:
            # ВНУТРЕННИЙ ПЕРЕВОД
            recipient_account.balance += transfer.amount
            category = "Перевод клиенту банка"
            to_id = recipient_account.id
        else:
            # ВНЕШНИЙ ПЕРЕВОД (Раз получатель не найден в базе аккаунтов, но номер карты есть)
            # Деньги уходят "в никуда" (эмуляция шлюза)
            category = f"Перевод на карту другого банка (*{clean_card[-4:]})"
            to_id = None

        tx = Transaction(
            from_account_id=sender_account.id,
            to_account_id=to_id,
            amount=transfer.amount,
            category=category
        )
        db.add(tx)
        await db.commit()
        
        return {"status": "success", "message": "Перевод выполнен"}

    except Exception as e:
        await db.rollback()
        print(e)
        raise HTTPException(status_code=500, detail="Ошибка транзакции")