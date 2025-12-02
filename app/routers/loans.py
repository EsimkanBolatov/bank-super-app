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
    type: str = "cash"  # cash, installment, bellyred, mortgage, auto
    # Для ипотеки
    property_value: float | None = None
    # Для автокредита
    vehicle_price: float | None = None

@router.post("/apply")
async def apply_loan(
        req: LoanRequest,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """Оформление кредита"""
    
    # 1. Определяем процентную ставку по типу кредита
    rates = {
        "cash": 0.15,          # Наличные: 15%
        "installment": 0.0,    # Рассрочка: 0%
        "bellyred": 0.0,       # Belly Red: 0%
        "red": 0.0,            # Алиас для bellyred
        "mortgage": 0.035,     # Ипотека: 3.5%
        "auto": 0.07           # Автокредит: 7%
    }
    
    rate = rates.get(req.type, 0.15)
    m_rate = rate / 12 if rate > 0 else 0
    
    amount_dec = Decimal(str(req.amount))
    
    # 2. Проверка дохода (Mock-скоринг)
    min_income_ratio = {
        "cash": 0.3,
        "installment": 0.2,
        "bellyred": 0.25,
        "red": 0.25,
        "mortgage": 0.4,
        "auto": 0.35
    }
    
    ratio = min_income_ratio.get(req.type, 0.3)
    
    # Расчет платежа
    if m_rate > 0:
        payment = amount_dec * Decimal(m_rate / (1 - (1 + m_rate) ** -req.term_months))
    else:
        payment = amount_dec / Decimal(req.term_months)
    
    # Проверка платежеспособности
    if float(payment) > req.income * ratio:
        raise HTTPException(
            status_code=400, 
            detail=f"Ваш доход недостаточен для кредита. Минимальный доход: {int(float(payment) / ratio)} ₸"
        )
    
    # 3. Дополнительные проверки
    if req.type == "mortgage":
        if not req.property_value or req.property_value < req.amount:
            raise HTTPException(status_code=400, detail="Стоимость недвижимости должна быть больше суммы кредита")
    
    if req.type == "auto":
        if not req.vehicle_price or req.vehicle_price < req.amount:
            raise HTTPException(status_code=400, detail="Стоимость авто должна быть больше суммы кредита")
    
    # 4. Поиск счета для зачисления
    q = select(Account).where(Account.user_id == current_user.id, Account.is_blocked == False)
    res = await db.execute(q)
    acc = res.scalars().first()
    
    if not acc:
        raise HTTPException(status_code=400, detail="Счет не найден")

    try:
        # 5. Создаем запись о кредите
        new_loan = Loan(
            user_id=current_user.id,
            amount=amount_dec,
            term_months=req.term_months,
            monthly_payment=payment,
            type=req.type,
            created_at=datetime.utcnow(),
            is_active=True
        )
        db.add(new_loan)
        await db.commit()
        await db.refresh(new_loan)

        # 6. Генерируем график платежей
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

        # 7. Зачисляем деньги на счет
        acc.balance += amount_dec
        
        # 8. Запись в транзакции
        category_names = {
            "cash": "Кредит наличными",
            "installment": "Рассрочка 0%",
            "bellyred": "Belly Red",
            "red": "Belly Red",
            "mortgage": "Ипотека",
            "auto": "Автокредит"
        }
        
        tx = Transaction(
            from_account_id=None,
            to_account_id=acc.id,
            amount=amount_dec,
            category=f"Зачисление: {category_names.get(req.type, 'Кредит')}",
            created_at=datetime.utcnow()
        )
        db.add(tx)
        
        await db.commit()
        
        return {
            "status": "approved",
            "message": "Кредит одобрен и зачислен на счет!",
            "loan_id": new_loan.id,
            "monthly_payment": float(payment),
            "total_amount": float(amount_dec * (1 + Decimal(str(rate * req.term_months / 12))))
        }

    except Exception as e:
        await db.rollback()
        print(f"Loan Error: {e}")
        raise HTTPException(status_code=500, detail="Ошибка оформления кредита")


@router.get("/my")
async def get_my_loans(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Список активных кредитов"""
    q = select(Loan).where(Loan.user_id == current_user.id, Loan.is_active == True)
    res = await db.execute(q)
    loans = res.scalars().all()
    
    result = []
    for loan in loans:
        # Считаем остаток долга
        q_paid = select(LoanSchedule).where(
            LoanSchedule.loan_id == loan.id,
            LoanSchedule.is_paid == False
        )
        res_paid = await db.execute(q_paid)
        unpaid = res_paid.scalars().all()
        
        remaining_amount = sum(float(p.amount) for p in unpaid)
        
        result.append({
            "id": loan.id,
            "type": loan.type,
            "amount": float(loan.amount),
            "monthly_payment": float(loan.monthly_payment),
            "term_months": loan.term_months,
            "remaining_amount": remaining_amount,
            "created_at": loan.created_at.isoformat()
        })
    
    return result


@router.get("/calendar")
async def get_payment_calendar(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """График платежей для календаря"""
    q_loans = select(Loan.id).where(Loan.user_id == current_user.id, Loan.is_active == True)
    res_loans = await db.execute(q_loans)
    loan_ids = res_loans.scalars().all()
    
    if not loan_ids:
        return {}

    q_sched = select(LoanSchedule).where(
        LoanSchedule.loan_id.in_(loan_ids),
        LoanSchedule.is_paid == False
    ).order_by(LoanSchedule.due_date)
    
    res_sched = await db.execute(q_sched)
    payments = res_sched.scalars().all()
    
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


@router.post("/{loan_id}/pay")
async def pay_loan_installment(
    loan_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Погашение ближайшего платежа"""
    
    # Проверяем кредит
    q_loan = select(Loan).where(Loan.id == loan_id, Loan.user_id == current_user.id)
    res_loan = await db.execute(q_loan)
    loan = res_loan.scalar_one_or_none()
    
    if not loan or not loan.is_active:
        raise HTTPException(status_code=404, detail="Кредит не найден")
    
    # Находим ближайший неоплаченный платеж
    q_next = select(LoanSchedule).where(
        LoanSchedule.loan_id == loan_id,
        LoanSchedule.is_paid == False
    ).order_by(LoanSchedule.due_date).limit(1)
    
    res_next = await db.execute(q_next)
    next_payment = res_next.scalar_one_or_none()
    
    if not next_payment:
        raise HTTPException(status_code=400, detail="Все платежи уже погашены")
    
    # Находим счет
    q_acc = select(Account).where(Account.user_id == current_user.id, Account.is_blocked == False)
    res_acc = await db.execute(q_acc)
    acc = res_acc.scalars().first()
    
    if not acc or acc.balance < next_payment.amount:
        raise HTTPException(status_code=400, detail="Недостаточно средств")
    
    try:
        # Списываем деньги
        acc.balance -= next_payment.amount
        next_payment.is_paid = True
        
        # Транзакция
        tx = Transaction(
            from_account_id=acc.id,
            to_account_id=None,
            amount=next_payment.amount,
            category=f"Погашение кредита ({loan.type})",
            created_at=datetime.utcnow()
        )
        db.add(tx)
        
        # Проверяем, все ли платежи погашены
        q_check = select(LoanSchedule).where(
            LoanSchedule.loan_id == loan_id,
            LoanSchedule.is_paid == False
        )
        res_check = await db.execute(q_check)
        remaining = res_check.scalars().all()
        
        if not remaining:
            loan.is_active = False
        
        await db.commit()
        
        return {
            "status": "success",
            "message": "Платеж проведен успешно!",
            "paid_amount": float(next_payment.amount),
            "loan_closed": not bool(remaining)
        }
        
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Ошибка платежа")