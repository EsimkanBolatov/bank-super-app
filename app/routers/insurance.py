from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from pydantic import BaseModel
from datetime import datetime, timedelta
from decimal import Decimal

from app.db.database import get_db
from app.db.models import User, Account, Transaction, Insurance
from app.dependencies import get_current_user

router = APIRouter(prefix="/insurance", tags=["Insurance"])


class InsuranceRequest(BaseModel):
    insurance_type: str  # life, health, property, auto, travel
    coverage_amount: float = 1000000  # Сумма покрытия
    term_months: int = 12


@router.post("/apply")
async def apply_insurance(
    req: InsuranceRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Оформление страхования"""
    
    # Тарифы (месячная стоимость на 1 млн покрытия)
    rates = {
        "life": 5000,      # Жизнь
        "health": 8000,    # Здоровье
        "property": 3000,  # Имущество
        "auto": 6000,      # Авто
        "travel": 2000     # Путешествия
    }
    
    base_cost = rates.get(req.insurance_type, 5000)
    
    # Рассчитываем стоимость с учетом суммы покрытия
    coverage_millions = req.coverage_amount / 1000000
    monthly_cost = Decimal(str(base_cost * coverage_millions))
    total_cost = monthly_cost * Decimal(str(req.term_months))
    
    # Находим счет
    q = select(Account).where(Account.user_id == current_user.id, Account.is_blocked == False)
    res = await db.execute(q)
    acc = res.scalars().first()
    
    if not acc:
        raise HTTPException(status_code=400, detail="Нет активного счета")
    
    if acc.balance < total_cost:
        raise HTTPException(status_code=400, detail="Недостаточно средств для оплаты страховки")
    
    try:
        # Списываем деньги
        acc.balance -= total_cost
        
        # Создаем полис
        end_date = datetime.utcnow() + timedelta(days=30 * req.term_months)
        
        new_insurance = Insurance(
            user_id=current_user.id,
            insurance_type=req.insurance_type,
            coverage_amount=Decimal(str(req.coverage_amount)),
            monthly_cost=monthly_cost,
            term_months=req.term_months,
            start_date=datetime.utcnow(),
            end_date=end_date,
            is_active=True
        )
        db.add(new_insurance)
        
        # Транзакция
        tx = Transaction(
            from_account_id=acc.id,
            to_account_id=None,
            amount=total_cost,
            category=f"Страхование: {req.insurance_type.upper()}",
            created_at=datetime.utcnow()
        )
        db.add(tx)
        
        await db.commit()
        await db.refresh(new_insurance)
        
        return {
            "status": "success",
            "message": "Страховка оформлена!",
            "policy_id": new_insurance.id,
            "total_cost": float(total_cost),
            "monthly_cost": float(monthly_cost)
        }
        
    except Exception as e:
        await db.rollback()
        print(f"Insurance Error: {e}")
        raise HTTPException(status_code=500, detail="Ошибка оформления страховки")


@router.get("/my")
async def get_my_insurances(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Список активных полисов"""
    q = select(Insurance).where(Insurance.user_id == current_user.id, Insurance.is_active == True)
    res = await db.execute(q)
    insurances = res.scalars().all()
    
    result = []
    for ins in insurances:
        result.append({
            "id": ins.id,
            "type": ins.insurance_type,
            "coverage": float(ins.coverage_amount),
            "monthly_cost": float(ins.monthly_cost),
            "term_months": ins.term_months,
            "start_date": ins.start_date.isoformat(),
            "end_date": ins.end_date.isoformat()
        })
    
    return result


@router.post("/{insurance_id}/cancel")
async def cancel_insurance(
    insurance_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Отмена страховки"""
    
    q = select(Insurance).where(Insurance.id == insurance_id, Insurance.user_id == current_user.id)
    res = await db.execute(q)
    insurance = res.scalar_one_or_none()
    
    if not insurance or not insurance.is_active:
        raise HTTPException(status_code=404, detail="Полис не найден")
    
    insurance.is_active = False
    await db.commit()
    
    return {"status": "success", "message": "Страховка отменена"}