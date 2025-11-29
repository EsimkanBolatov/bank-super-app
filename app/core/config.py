import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator


class Settings(BaseSettings):
    # --- НАСТРОЙКИ БАЗЫ ДАННЫХ (Для локальной разработки) ---
    # Делаем их необязательными (None), чтобы на Railway не падала ошибка валидации.
    DB_USER: str | None = None
    DB_PASSWORD: str | None = None
    DB_HOST: str | None = None
    DB_PORT: str | None = None
    DB_NAME: str | None = None

    # --- ОСНОВНЫЕ ПЕРЕМЕННЫЕ ---
    SECRET_KEY: str = "dev_secret_key"  # Дефолт для локалки, в проде будет перезаписан
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    GROQ_API_KEY: str = ""  # Если пусто, то просто не будет работать AI, но приложение запустится

    # --- ГЛАВНАЯ ПЕРЕМЕННАЯ (Для продакшена/Railway) ---
    # Если Railway предоставит эту переменную, мы будем использовать её.
    # Если нет (локально), мы соберем её сами из кусков выше.
    DATABASE_URL: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # --- УМНЫЙ ВАЛИДАТОР ---
    # Этот метод запускается ПОСЛЕ загрузки всех переменных.
    # Он решает, как сформировать итоговый DATABASE_URL.
    @model_validator(mode='after')
    def assemble_db_connection(self):
        # 1. Если DATABASE_URL уже есть (например, от Railway), просто проверяем формат
        if self.DATABASE_URL:
            # Railway часто дает ссылку вида "postgres://...",
            # но SQLAlchemy (asyncpg) требует "postgresql+asyncpg://..."
            if self.DATABASE_URL.startswith("postgres://"):
                self.DATABASE_URL = self.DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
            return self

        # 2. Если DATABASE_URL нет, собираем его из локальных переменных
        # (Это сработает для Docker Compose, где заданы DB_USER, DB_PASSWORD и т.д.)
        if self.DB_USER and self.DB_HOST and self.DB_NAME:
            self.DATABASE_URL = (
                f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}@"
                f"{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
            )
        else:
            # Если нет ни URL, ни частей — ставим заглушку (чтобы приложение не крашилось сразу, а упало только при подключении к БД)
            # Это полезно для отладки CI/CD
            self.DATABASE_URL = "postgresql+asyncpg://user:pass@localhost/dbname"
            print("WARNING: Database config not found. Using dummy URL.")

        return self


settings = Settings()