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

async def get_or_create_service_account(db: AsyncSession, service_name: str) -> Account:
    # Для упрощения все деньги уходят на один "технический" аккаунт сервисов
    # В реальности тут была бы сложная логика маршрутизации
    service_phone = "srv_general"
    
    q = select(User).where(User.phone == service_phone)
    res = await db.execute(q)
    user = res.scalars().first()

    if not user:
        user = User(phone=service_phone, password_hash="pass", full_name="Service Hub", role=RoleEnum.USER)
        db.add(user)
        await db.commit()
        await db.refresh(user)

    q_acc = select(Account).where(Account.user_id == user.id)
    res_acc = await db.execute(q_acc)
    acc = res_acc.scalars().first()

    if not acc:
        acc = Account(user_id=user.id, card_number="SRV_000_000", balance=0, currency=CurrencyEnum.KZT)
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

    # --- ФОРМИРОВАНИЕ КРАСИВОГО ОПИСАНИЯ ---
    desc = f"Оплата: {req.service_name}"
    dt = req.details or {}
 
    if req.service_name == "Мобильный":
        desc = f"Моб: {dt.get('operator', '').upper()} ({dt.get('phone', '')})"
    
    elif req.service_name == "Коммуналка":
        desc = f"ЖКХ: {dt.get('service_type', '').upper()} ({dt.get('account_id', '')})"
        
    elif req.service_name == "Транспорт":
        desc = f"Транспорт: {dt.get('city', '').upper()} ({dt.get('card_number', '')})"
        
    elif req.service_name == "Интернет и ТВ":
        provider = dt.get('provider', '').replace('_', ' ').title()
        desc = f"Интернет: {provider} ({dt.get('account_id', '')})"
        
    elif req.service_name == "Образование":
        uni = dt.get('university', '').upper()
        desc = f"Обучение: {uni} (ID: {dt.get('student_id', '')})"
        
    elif req.service_name == "Билеты":
        srv = dt.get('ticket_service', '').replace('_', ' ').title()
        desc = f"Билеты: {srv} (Заказ: {dt.get('order_id', '')})"
        
    elif req.service_name == "Покупки":
        shop = dt.get('shop', '').title()
        desc = f"Shop: {shop} (Заказ: {dt.get('order_id', '')})"
        
    elif req.service_name == "Развлечения":
        srv = dt.get('service', '').replace('_', ' ').title()
        desc = f"Подписка: {srv} ({dt.get('username', '')})"
        
    elif req.service_name == "Штрафы":
        search_type = "ИИН" if dt.get('search_type') == 'iin' else "Госномер"
        desc = f"Штраф ({search_type}): {dt.get('search_value', '')}"
        
    elif req.service_name == "Другое":
        cat = dt.get('category', 'Прочее')
        text = dt.get('description', '')
        desc = f"{cat}: {text}"
        
    elif req.service_name == "Eco Tree":
        desc = "Вклад в экологию 🌳"
        
    elif req.service_name == "Ortak":
        desc = "Ortak: Разделение счета 🍕"

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
        print(f"Payment Error: {e}")
        raise HTTPException(status_code=500, detail="Ошибка при проведении платежа")