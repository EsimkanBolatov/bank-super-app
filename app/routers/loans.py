from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from pydantic import BaseModel
from datetime import datetime, timedelta
from decimal import Decimal

from app.db.database import get_db
from app.db.models import User, Account, Transaction, Loan, LoanSchedule
from app.dependencies import get_current_user

router = APIRouter(prefix="/loans", tags=["Loans"])

class LoanRequest(BaseModel):
    amount: float
    term_months: int
    income: float
    type: str = "credit" # "credit" или "red"

@router.post("/apply")
async def apply_loan(
        req: LoanRequest,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    # 1. Расчет ставки
    rate = 0.0 if req.type == "red" else 0.15 # Red = 0%, Кредит = 15%
    m_rate = rate / 12
    
    amount_dec = Decimal(str(req.amount))
    
    if m_rate > 0:
        payment = amount_dec * Decimal(m_rate / (1 - (1 + m_rate) ** -req.term_months))
    else:
        payment = amount_dec / Decimal(req.term_months)

    # 2. Поиск счета для зачисления
    q = select(Account).where(Account.user_id == current_user.id)
    res = await db.execute(q)
    acc = res.scalars().first()
    
    if not acc:
        raise HTTPException(status_code=400, detail="Счет не найден")

    try:
        # 3. Создаем запись о кредите
        new_loan = Loan(
            user_id=current_user.id,
            amount=amount_dec,
            term_months=req.term_months,
            monthly_payment=payment,
            type=req.type,
            created_at=datetime.utcnow()
        )
        db.add(new_loan)
        await db.commit() # Чтобы получить ID кредита
        await db.refresh(new_loan)

        # 4. Генерируем график платежей в БД
        curr = datetime.utcnow()
        for i in range(1, req.term_months + 1):
            due_date = curr + timedelta(days=30 * i)
            schedule_item = LoanSchedule(
                loan_id=new_loan.id,
                due_date=due_date,
                amount=payment,
                is_paid=False
            )
            db.add(schedule_item)

        # 5. Зачисляем деньги на счет
        acc.balance += amount_dec
        
        # 6. Запись в транзакции
        tx = Transaction(
            from_account_id=None,
            to_account_id=acc.id,
            amount=amount_dec,
            category=f"Зачисление {'Belly Red' if req.type == 'red' else 'Кредита'}",
            created_at=datetime.utcnow()
        )
        db.add(tx)
        
        await db.commit()
        
        return {"status": "approved", "message": "Одобрено и зачислено!"}

    except Exception as e:
        await db.rollback()
        print(f"Loan Error: {e}")
        raise HTTPException(status_code=500, detail="Ошибка оформления")

# --- ЭНДПОИНТ ДЛЯ КАЛЕНДАРЯ ---
@router.get("/calendar")
async def get_payment_calendar(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Ищем все активные кредиты юзера
    q_loans = select(Loan.id).where(Loan.user_id == current_user.id, Loan.is_active == True)
    res_loans = await db.execute(q_loans)
    loan_ids = res_loans.scalars().all()
    
    if not loan_ids:
        return []

    # Ищем неоплаченные платежи по этим кредитам
    q_sched = select(LoanSchedule).where(
        LoanSchedule.loan_id.in_(loan_ids),
        LoanSchedule.is_paid == False
    ).order_by(LoanSchedule.due_date)
    
    res_sched = await db.execute(q_sched)
    payments = res_sched.scalars().all()
    
    # Формируем ответ для календаря React Native
    # Формат: { "2025-12-25": {marked: true, dotColor: 'red', amount: 5000} }
    calendar_data = {}
    
    for p in payments:
        date_str = p.due_date.strftime("%Y-%m-%d")
        calendar_data[date_str] = {
            "amount": float(p.amount),
            "marked": True, 
            "dotColor": "red",
            "activeOpacity": 0
        }
        
    return calendar_data