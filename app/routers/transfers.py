from fastapi import APIRouter, Depends, HTTPException
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

# --- ИЗБРАННОЕ ---
@router.get("/favorites")
async def get_favorites(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        res = await db.execute(select(Favorite).where(Favorite.user_id == current_user.id))
        return [{"id": f.id, "name": f.name, "value": f.value, "type": f.type, "color": [f.color_start, f.color_end]} for f in res.scalars().all()]
    except Exception:
        return [] 

@router.post("/favorites")
async def add_favorite(fav: FavoriteCreate, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    # Сохраняем избранное с дефолтными цветами (можно рандомизировать)
    new_fav = Favorite(
        user_id=current_user.id, 
        name=fav.name, 
        value=fav.value, 
        type=fav.type,
        color_start="#FFA726",
        color_end="#FB8C00"
    )
    db.add(new_fav)
    await db.commit()
    return {"status": "ok", "id": new_fav.id}

@router.delete("/favorites/{fav_id}")
async def delete_favorite(fav_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    res = await db.execute(select(Favorite).where(Favorite.id == fav_id, Favorite.user_id == current_user.id))
    if fav := res.scalar_one_or_none():
        await db.delete(fav)
        await db.commit()
    return {"status": "ok"}

# --- ПЕРЕВОДЫ ---
@router.post("/p2p")
async def make_transfer(
        transfer: TransferRequest,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    # 1. ОТПРАВИТЕЛЬ
    sender_account = None
    
    # Если карта выбрана явно (из UI)
    if transfer.from_account_id:
        res = await db.execute(select(Account).where(Account.id == transfer.from_account_id, Account.user_id == current_user.id))
        sender_account = res.scalar_one_or_none()
    
    # Если карта НЕ выбрана (например, через AI), ищем подходящую
    if not sender_account:
        # Получаем все активные карты пользователя
        res = await db.execute(select(Account).where(Account.user_id == current_user.id, Account.is_blocked == False))
        accounts = res.scalars().all()
        
        # Ищем первую карту, где хватает денег
        for acc in accounts:
            if acc.balance >= transfer.amount:
                sender_account = acc
                break
        
        # Если подходящей нет, берем первую (чтобы вернуть ошибку "Недостаточно средств" именно по ней)
        if not sender_account and accounts:
            sender_account = accounts[0]

    if not sender_account:
        raise HTTPException(status_code=400, detail="Нет карты для списания")
    if sender_account.is_blocked:
        raise HTTPException(status_code=403, detail="Карта списания заблокирована")
    if sender_account.balance < transfer.amount:
        raise HTTPException(status_code=400, detail="Недостаточно средств")

    # 2. ПОЛУЧАТЕЛЬ
    recipient_account = None
    
    # Улучшенная очистка номера
    clean_phone = None
    if transfer.to_phone:
        # Убираем все лишнее
        clean_phone = transfer.to_phone.replace(" ", "").replace("+", "").replace("-", "").replace("(", "").replace(")", "")
        # Нормализуем к виду 8777...
        if len(clean_phone) == 11 and clean_phone.startswith("7"):
            clean_phone = "8" + clean_phone[1:]
        elif len(clean_phone) == 10:
            clean_phone = "8" + clean_phone

    clean_card = transfer.to_card.replace(" ", "") if transfer.to_card else None

    if clean_phone:
        # Поиск по телефону
        res = await db.execute(select(User).where(User.phone == clean_phone).options(selectinload(User.accounts)))
        recipient_user = res.scalar_one_or_none()
        
        if not recipient_user:
            raise HTTPException(status_code=404, detail="Клиент не найден")
            
        # Ищем у получателя карту для зачисления (не заблокированную)
        for acc in recipient_user.accounts:
            if not acc.is_blocked:
                recipient_account = acc
                break
        
        if not recipient_account and recipient_user.accounts:
             # Если все заблокированы, берем первую
             recipient_account = recipient_user.accounts[0]
             
        if not recipient_account:
            raise HTTPException(status_code=400, detail="У получателя нет активных карт")

    elif clean_card:
        # Поиск по карте
        res = await db.execute(select(Account).where(Account.card_number == clean_card))
        recipient_account = res.scalar_one_or_none()

    # 3. ПРОВЕРКА (Нельзя самому себе на ту же карту)
    if recipient_account and sender_account.id == recipient_account.id:
        raise HTTPException(status_code=400, detail="Перевод на ту же карту невозможен")

    # 4. ТРАНЗАКЦИЯ
    try:
        sender_account.balance -= transfer.amount
        
        if recipient_account:
            recipient_account.balance += transfer.amount
            desc = "Перевод клиенту"
        else:
            # Внешний перевод
            desc = f"Перевод на карту др. банка (*{clean_card[-4:] if clean_card else 'EXT'})"

        tx = Transaction(
            from_account_id=sender_account.id,
            to_account_id=recipient_account.id if recipient_account else None,
            amount=transfer.amount,
            category=desc
        )
        db.add(tx)
        await db.commit()
        return {"status": "success", "message": "Перевод отправлен"}
    except Exception as e:
        await db.rollback()
        print(f"Transfer Error: {e}")
        raise HTTPException(status_code=500, detail="Ошибка транзакции")