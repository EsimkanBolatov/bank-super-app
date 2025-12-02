import os
import json
import shutil
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from groq import Groq

from app.core.config import settings
from app.db.database import get_db
from app.db.models import User, Account
from app.dependencies import get_current_user

router = APIRouter(prefix="/ai", tags=["AI Assistant"])

client = Groq(api_key=settings.GROQ_API_KEY)


# --- Новая модель ответа ---
class ChatResponse(BaseModel):
    reply: str  # Текст, который скажет ассистент
    action: str | None = None  # Тип действия: "transfer" или None
    data: dict | None = None  # Данные для действия: {amount, phone}


@router.post("/voice", response_model=ChatResponse)
async def voice_chat(
        file: UploadFile = File(...),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    # 1. Сохраняем аудио файл временно
    temp_filename = f"voice_{current_user.id}.m4a"
    with open(temp_filename, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        # 2. Распознавание речи (Whisper через Groq)
        with open(temp_filename, "rb") as audio_file:
            transcription = client.audio.transcriptions.create(
                file=(temp_filename, audio_file.read()),
                model="whisper-large-v3",
                response_format="json",
                language="ru"  # Или auto
            )
        user_text = transcription.text
        print(f"User said: {user_text}")

        # Обрабатываем текст как команду
        return await process_command(user_text, db, current_user)

    except Exception as e:
        print(f"Voice Error: {e}")
        return {"reply": "Не удалось распознать голос."}
    finally:
        if os.path.exists(temp_filename):
            os.remove(temp_filename)


@router.post("/chat", response_model=ChatResponse)
async def text_chat(
        request: dict,  # Простой wrapper {message: str}
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    return await process_command(request.get("message", ""), db, current_user)


async def process_command(user_text: str, db: AsyncSession, user: User):
    # Получаем контекст (баланс)
    query = select(Account).where(Account.user_id == user.id)
    result = await db.execute(query)
    accounts = result.scalars().all()

    finance_context = "Баланс пользователя:\n"
    for acc in accounts:
        finance_context += f"- Карта *{acc.card_number[-4:]}: {acc.balance} {acc.currency}\n"

    # --- УЛУЧШЕННЫЙ ПРОМПТ ---
    system_prompt = (
        "Ты — голосовой ассистент банка BellyBank. "
        f"{finance_context}\n"
        "Твоя задача: определить намерение пользователя из текста.\n\n"
        "ПРАВИЛА ДЛЯ ПЕРЕВОДА:\n"
        "1. Если пользователь хочет сделать ПЕРЕВОД и указал СУММУ и НОМЕР (телефона или карты), верни JSON:\n"
        "   {\"action\": \"transfer\", \"amount\": 500, \"phone\": \"8747...\", \"reply\": \"Хорошо, перевожу 500 тенге...\"}\n"
        "   - Номер телефона всегда приводи к формату: 11 цифр, начинается с 8 (например 87471234567).\n"
        "   - Если пользователь сказал 'на номер 707...', добавь 8 в начало: 8707...\n"
        "   - Убери все пробелы и лишние символы из номера.\n\n"
        "2. Если пользователь НЕ указал сумму или номер, НЕ придумывай их. Верни JSON:\n"
        "   {\"action\": null, \"reply\": \"Пожалуйста, уточните сумму и номер телефона.\"}\n\n"
        "3. Для обычных вопросов верни JSON:\n"
        "   {\"action\": null, \"reply\": \"Твой ответ...\"}\n\n"
        "Всегда возвращай только валидный JSON."
    )

    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text}
            ],
            model="llama-3.1-8b-instant",
            temperature=0,
            response_format={"type": "json_object"}
        )

        response_content = chat_completion.choices[0].message.content
        ai_data = json.loads(response_content)

        return {
            "reply": ai_data.get("reply", "Готово"),
            "action": ai_data.get("action"),
            "data": {
                "amount": ai_data.get("amount"),
                "phone": ai_data.get("phone")
            } if ai_data.get("action") == "transfer" else None
        }

    except Exception as e:
        print(f"AI Error: {e}")
        return {"reply": "Произошла ошибка при обработке команды."}
