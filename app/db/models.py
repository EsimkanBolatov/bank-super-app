import enum
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Enum, Numeric, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.database import Base


class CurrencyEnum(str, enum.Enum):
    KZT = "KZT"
    USD = "USD"
    EUR = "EUR"


class RoleEnum(str, enum.Enum):
    USER = "user"
    ADMIN = "admin"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    phone = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    full_name = Column(String, nullable=True)
    # --- НОВОЕ ПОЛЕ ---
    avatar_url = Column(String, nullable=True)
    role = Column(Enum(RoleEnum), default=RoleEnum.USER)

    accounts = relationship("Account", back_populates="owner")


class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    card_number = Column(String(30), unique=True, index=True, nullable=False)
    balance = Column(Numeric(10, 2), default=0.00)
    currency = Column(Enum(CurrencyEnum), default=CurrencyEnum.KZT)
    is_blocked = Column(Boolean, default=False)

    owner = relationship("User", back_populates="accounts")

    outgoing_transactions = relationship("Transaction", foreign_keys="Transaction.from_account_id",
                                         back_populates="from_account")
    incoming_transactions = relationship("Transaction", foreign_keys="Transaction.to_account_id",
                                         back_populates="to_account")

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    from_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    to_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    amount = Column(Numeric(10, 2), nullable=False)
    category = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Связи (Relationships)
    from_account = relationship("Account", foreign_keys=[from_account_id], back_populates="outgoing_transactions")
    to_account = relationship("Account", foreign_keys=[to_account_id], back_populates="incoming_transactions")

class Loan(Base):  # <--- ТУТ БЫЛА ОШИБКА, НУЖНО Base
    __tablename__ = "loans"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    term_months = Column(Integer, nullable=False)
    monthly_payment = Column(Numeric(10, 2), nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    type = Column(String, default="credit") # "credit" или "red"

    schedule = relationship("LoanSchedule", back_populates="loan")


class LoanSchedule(Base):  
    __tablename__ = "loan_schedules"

    id = Column(Integer, primary_key=True, index=True)
    loan_id = Column(Integer, ForeignKey("loans.id"), nullable=False)
    due_date = Column(DateTime(timezone=True), nullable=False) # Когда платить
    amount = Column(Numeric(10, 2), nullable=False)
    is_paid = Column(Boolean, default=False)

    loan = relationship("Loan", back_populates="schedule")

class Favorite(Base):
    __tablename__ = "favorites"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)      # Имя (Мама, Аренда)
    value = Column(String, nullable=False)     # Номер телефона или карты
    type = Column(String, nullable=False)      # "phone" или "card"
    color_start = Column(String, default="#4CAF50") # Для градиента
    color_end = Column(String, default="#2E7D32")

class Deposit(Base):
    """Модель вклада"""
    __tablename__ = "deposits"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)  # Сумма вклада
    rate = Column(Numeric(5, 4), nullable=False)  # Процентная ставка (например, 0.16 = 16%)
    term_months = Column(Integer, nullable=False)  # Срок в месяцах
    type = Column(String, default="standard")  # standard, premium, vip
    start_date = Column(DateTime(timezone=True), default=datetime.utcnow)
    end_date = Column(DateTime(timezone=True), nullable=False)
    is_active = Column(Boolean, default=True)


class Insurance(Base):
    """Модель страхования"""
    __tablename__ = "insurances"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    insurance_type = Column(String, nullable=False)  # life, health, property, auto, travel
    coverage_amount = Column(Numeric(12, 2), nullable=False)  # Сумма покрытия
    monthly_cost = Column(Numeric(10, 2), nullable=False)  # Ежемесячная стоимость
    term_months = Column(Integer, nullable=False)
    start_date = Column(DateTime(timezone=True), default=datetime.utcnow)
    end_date = Column(DateTime(timezone=True), nullable=False)
    is_active = Column(Boolean, default=True)