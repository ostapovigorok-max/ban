# Telegram Moderation Bot

Async Python 3.12 Telegram moderation bot built with aiogram 3.x, SQLAlchemy, SQLite and Alembic.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
alembic upgrade head
python -m app
```

## Docker

```bash
docker compose up --build
```

## Required bot permissions

The bot must be an administrator in moderated groups with permissions to send messages, delete messages and restrict members.

## Configuration

Configuration is read from `.env`. Required subscription IDs must be numeric Telegram chat IDs and are used only for `getChatMember()` checks.
