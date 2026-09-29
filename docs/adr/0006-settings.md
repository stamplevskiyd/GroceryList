# ADR-0006. Конфигурация — pydantic-settings в одном модуле

Статус: принято · Дата: 2026-09-29

## Контекст

Настройки: адрес БД, публичный URL (от него зависят OAuth metadata и MCP), секрет сессий,
VAPID-ключи, сроки жизни токенов, параметры push-повторов. Они приходят из `.env` и переменных
окружения docker-compose (спец. §9–10). Разрозненные `os.environ.get(...)` по коду дают неявные
значения по умолчанию и падение в момент первого использования, а не при старте.

## Решение

Один файл `config.py`: корневой класс `Settings` (единственный `BaseSettings`) и группы
настроек по областям — обычные `BaseModel`, все в этом же файле.

```python
class AppSettings(BaseModel):
    public_url: HttpUrl
    log_level: str = "INFO"

class DbSettings(BaseModel):
    url: PostgresDsn

class AuthSettings(BaseModel):
    session_secret: SecretStr
    session_ttl: timedelta = timedelta(days=30)
    access_token_ttl: timedelta = timedelta(hours=1)
    refresh_token_ttl: timedelta = timedelta(days=30)

class PushSettings(BaseModel):
    vapid_private_key: SecretStr
    vapid_public_key: str
    vapid_contact: str
    max_attempts: int = 5

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="_",
        env_nested_max_split=1,       # делим только по первому «_»
        extra="ignore",
    )
    app: AppSettings
    db: DbSettings
    auth: AuthSettings
    push: PushSettings

@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- **Имена переменных — с одним разделителем:** `<ГРУППА>_<ПОЛЕ>`. `DB_URL` → `settings.db.url`,
  `AUTH_SESSION_SECRET` → `settings.auth.session_secret`, `PUSH_VAPID_PUBLIC_KEY` →
  `settings.push.vapid_public_key`. `env_nested_max_split=1` делит имя только по первому `_`,
  поэтому поля с подчёркиваниями внутри работают. Имя группы — одно слово без `_`.
- **Доступ — только `get_settings()`** из `config.py`. Чтение `os.environ` в других модулях
  запрещено. Функция, а не глобальный объект: импорт модуля не требует готового окружения
  (тесты, CLI, генерация OpenAPI), а тесты сбрасывают кэш `get_settings.cache_clear()`.
- `get_settings()` вызывается в `lifespan` при старте — неполная конфигурация роняет приложение
  сразу, с ошибкой, указывающей на поле (`auth.session_secret: Field required`).
- Секреты — `SecretStr`; в логах и `repr` не раскрываются.
- Значения по умолчанию есть только у того, что безопасно и одинаково для разработки и продакшена.
  Секреты и адреса — без умолчаний.
- `.env.example` в репозитории перечисляет все переменные; `.env` — в `.gitignore`.

## Рассмотренные альтернативы

- **Несколько `BaseSettings` с `env_prefix`** (`DB_`, `AUTH_`) и сборка их в корневой объект —
  те же имена переменных, но несколько классов-источников и ручная сборка.
- **Вложенный разделитель `__`** (`DB__URL`) — не нужен: `env_nested_max_split=1`
  (pydantic-settings ≥ 2.8) снимает неоднозначность одинарного `_`.

## Последствия

- Все переменные окружения видны в одном файле; `.env.example` проверяем по нему.
- Новая группа настроек — новый `BaseModel` и поле в `Settings`.

## Как проверяется

- Ruff: запрет `os.environ` / `os.getenv` вне `config.py` (`TID251` banned-api).
- Тест: каждое поле `Settings` (в виде `<ГРУППА>_<ПОЛЕ>`) есть в `.env.example`.
- Тест: имена групп не содержат `_`.
