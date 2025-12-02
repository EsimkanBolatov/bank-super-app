from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from pydantic import BaseModel
from decimal import Decimal
from datetime import datetime
from typing import Dict, Optional, Any

from app.db.database import get_db
from app.db.models import User, Account, Transaction, RoleEnum, CurrencyEnum
from app.dependencies import get_current_user

router = APIRouter(prefix="/services", tags=["Services"])

class PayServiceRequest(BaseModel):
    service_name: str
    amount: float
    details: Optional[Dict[str, Any]] = None

# НАСТРОЙКА: Куда уходят деньги
SERVICE_ACCOUNTS_MAP = {
    # --- СТАНДАРТНЫЕ ПЛАТЕЖИ ---
    "Мобильный": {"phone": "srv_mobile", "name": "Mobile Hub", "card": "MOB_001"},
    "Коммуналка": {"phone": "srv_util", "name": "Utility Center", "card": "UTL_001"},
    "Транспорт": {"phone": "srv_trans", "name": "City Transport", "card": "TRN_001"},
    "Штрафы": {"phone": "srv_fines", "name": "Gov Fines", "card": "GOV_001"},
    "Интернет и ТВ": {"phone": "srv_inet", "name": "Internet Providers", "card": "INET_ACC"},
    "Образование": {"phone": "srv_edu", "name": "Education Hub", "card": "EDU_ACC"},
    "Игры": {"phone": "srv_games", "name": "Game Stores", "card": "GAM_001"},
    "Билеты": {"phone": "service_ticket", "name": "Ticketon", "card": "TICKET_ACC"},
    "Покупки": {"phone": "service_shop", "name": "E-Commerce", "card": "SHOP_ACC"},
    "Развлечения": {"phone": "service_fun", "name": "Entertainment", "card": "FUN_ACC"},
    "Объявления": {"phone": "srv_ads", "name": "Ads Platform", "card": "ADS_001"},
    "Красота": {"phone": "srv_beauty", "name": "Beauty Hub", "card": "BTY_001"},
    "Финансы": {"phone": "srv_fin", "name": "Fin Services", "card": "FIN_001"},
    
    # --- УНИКАЛЬНЫЕ СЕРВИСЫ (SUPER APP) ---
    "Eco Tree": {"phone": "srv_eco", "name": "Eco Fund KZ", "card": "ECO_001"},
    "Ortak": {"phone": "srv_ortak", "name": "P2P Split System", "card": "ORTAK_001"},
    
    # Дефолт
    "Другое": {"phone": "srv_other", "name": "Other Services", "card": "OTH_001"},
}

async def get_or_create_service_account(db: AsyncSession, service_name: str) -> Account:
    info = SERVICE_ACCOUNTS_MAP.get(service_name, SERVICE_ACCOUNTS_MAP["Другое"])
    
    q = select(User).where(User.phone == info["phone"])
    res = await db.execute(q)
    user = res.scalars().first()

    if not user:
        user = User(phone=info["phone"], password_hash="pass", full_name=info["name"], role=RoleEnum.USER)
        db.add(user)
        await db.commit()
        await db.refresh(user)

    q_acc = select(Account).where(Account.user_id == user.id)
    res_acc = await db.execute(q_acc)
    acc = res_acc.scalars().first()

    if not acc:
        acc = Account(user_id=user.id, card_number=info["card"], balance=0, currency=CurrencyEnum.KZT)
        db.add(acc)
        await db.commit()
        await db.refresh(acc)

    return acc

@router.post("/pay")
async def pay_service(
        req: PayServiceRequest,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    q = select(Account).where(Account.user_id == current_user.id, Account.is_blocked == False)
    res = await db.execute(q)
    user_acc = res.scalars().first()

    if not user_acc:
        raise HTTPException(status_code=400, detail="Нет активного счета")

    amount = Decimal(str(req.amount))
    if user_acc.balance < amount:
        raise HTTPException(status_code=400, detail="Недостаточно средств")

    service_acc = await get_or_create_service_account(db, req.service_name)

    # Формирование описания транзакции
    desc = f"Оплата: {req.service_name}"
    dt = req.details or {}

    if req.service_name == "Мобильный":
        desc = f"Моб: {dt.get('operator', '').upper()} {dt.get('phone', '')}"
    elif req.service_name == "Коммуналка":
        desc = f"ЖКХ: {dt.get('service', '').upper()} ({dt.get('account', '')})"
    elif req.service_name == "Транспорт":
        desc = f"Транспорт: {dt.get('city', '')} ({dt.get('card', '')})"
    elif req.service_name == "Штрафы":
        desc = f"Штраф: {dt.get('type', '')} {dt.get('value', '')}"
    elif req.service_name == "Eco Tree":
        desc = "Вклад в экологию 🌳"
    elif req.service_name == "Ortak":
        desc = "Возврат долга (Split) 🍕"

    try:
        user_acc.balance -= amount
        service_acc.balance += amount

        tx = Transaction(
            from_account_id=user_acc.id,
            to_account_id=service_acc.id,
            amount=amount,
            category=desc,
            created_at=datetime.utcnow()
        )
        db.add(tx)
        await db.commit()
        
        return {"status": "success", "message": desc, "new_balance": float(user_acc.balance)}

    except Exception as e:
        await db.rollback()
        print(e)
        raise HTTPException(status_code=500, detail="Ошибка платежа")