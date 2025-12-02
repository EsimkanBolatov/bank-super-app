from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from pydantic import BaseModel
from datetime import datetime, timedelta
from decimal import Decimal

from app.db.database import get_db
from app.db.models import User, Account, Transaction, Deposit
from app.dependencies import get_current_user

router = APIRouter(prefix="/deposits", tags=["Deposits"])


class DepositRequest(BaseModel):
    amount: float
    term_months: int
    type: str = "standard"  # standard, premium, vip


@router.post("/create")
async def create_deposit(
    req: DepositRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Открытие вклада"""
    
    # 1. Определяем ставку по типу
    rates = {
        "standard": 0.12,  # 12%
        "premium": 0.14,   # 14%
        "vip": 0.16        # 16%
    }
    rate = rates.get(req.type, 0.12)
    
    amount_dec = Decimal(str(req.amount))
    
    if amount_dec <= 0:
        raise HTTPException(status_code=400, detail="Сумма должна быть больше 0")
    
    # 2. Находим счет для списания
    q = select(Account).where(Account.user_id == current_user.id, Account.is_blocked == False)
    res = await db.execute(q)
    acc = res.scalars().first()
    
    if not acc:
        raise HTTPException(status_code=400, detail="Нет активного счета")
    
    if acc.balance < amount_dec:
        raise HTTPException(status_code=400, detail="Недостаточно средств")
    
    try:
        # 3. Списываем деньги со счета
        acc.balance -= amount_dec
        
        # 4. Создаем запись о вкладе
        end_date = datetime.utcnow() + timedelta(days=30 * req.term_months)
        
        new_deposit = Deposit(
            user_id=current_user.id,
            amount=amount_dec,
            rate=Decimal(str(rate)),
            term_months=req.term_months,
            type=req.type,
            start_date=datetime.utcnow(),
            end_date=end_date,
            is_active=True
        )
        db.add(new_deposit)
        
        # 5. Транзакция
        tx = Transaction(
            from_account_id=acc.id,
            to_account_id=None,
            amount=amount_dec,
            category=f"Открытие вклада ({req.type.upper()})",
            created_at=datetime.utcnow()
        )
        db.add(tx)
        
        await db.commit()
        await db.refresh(new_deposit)
        
        # Рассчитываем будущий доход
        total_income = amount_dec * Decimal(str(rate)) * Decimal(str(req.term_months / 12))
        
        return {
            "status": "success",
            "message": "Вклад открыт!",
            "deposit_id": new_deposit.id,
            "estimated_income": float(total_income)
        }
        
    except Exception as e:
        await db.rollback()
        print(f"Deposit Error: {e}")
        raise HTTPException(status_code=500, detail="Ошибка открытия вклада")


@router.get("/my")
async def get_my_deposits(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Список активных вкладов"""
    q = select(Deposit).where(Deposit.user_id == current_user.id, Deposit.is_active == True)
    res = await db.execute(q)
    deposits = res.scalars().all()
    
    result = []
    for dep in deposits:
        # Считаем текущий доход
        days_passed = (datetime.utcnow() - dep.start_date).days
        months_passed = days_passed / 30
        current_income = dep.amount * dep.rate * Decimal(str(months_passed / 12))
        
        result.append({
            "id": dep.id,
            "amount": float(dep.amount),
            "rate": float(dep.rate) * 100,
            "term_months": dep.term_months,
            "type": dep.type,
            "start_date": dep.start_date.isoformat(),
            "end_date": dep.end_date.isoformat(),
            "current_income": float(current_income)
        })
    
    return result


@router.post("/{deposit_id}/close")
async def close_deposit(
    deposit_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Досрочное закрытие вклада (с потерей процентов)"""
    
    q = select(Deposit).where(Deposit.id == deposit_id, Deposit.user_id == current_user.id)
    res = await db.execute(q)
    deposit = res.scalar_one_or_none()
    
    if not deposit or not deposit.is_active:
        raise HTTPException(status_code=404, detail="Вклад не найден")
    
    # Находим счет для возврата средств
    q_acc = select(Account).where(Account.user_id == current_user.id).limit(1)
    res_acc = await db.execute(q_acc)
    acc = res_acc.scalar_one_or_none()
    
    if not acc:
        raise HTTPException(status_code=400, detail="Счет не найден")
    
    try:
        # Возвращаем только основную сумму (без процентов при досрочном закрытии)
        acc.balance += deposit.amount
        deposit.is_active = False
        
        tx = Transaction(
            from_account_id=None,
            to_account_id=acc.id,
            amount=deposit.amount,
            category="Закрытие вклада (досрочно)",
            created_at=datetime.utcnow()
        )
        db.add(tx)
        
        await db.commit()
        
        return {
            "status": "success",
            "message": "Вклад закрыт. Средства возвращены на счет.",
            "returned_amount": float(deposit.amount)
        }
        
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Ошибка закрытия вклада")