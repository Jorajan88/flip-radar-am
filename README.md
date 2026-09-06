# 🏠 Flip Radar AM

Автоматический сканер аренды на list.am — находит объекты на 15%+ ниже медианы района.

## Что умеет
- Парсит list.am через Playwright (обходит Cloudflare)
- Считает медианную цену за м² по каждому району Еревана
- Отправляет сигналы в Telegram-канал
- Отслеживает снижения цен (📉)
- Автоочистка базы (старше 15 дней)
- Cron-автозапуск 2 раза в день

## Стек
- Python 3.12
- Playwright (Chromium)
- SQLite
- Telegram Bot API
- Ubuntu VPS

## Запуск локально
```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
.venv/Scripts/playwright install chromium
.venv/Scripts/python radar.py

Деплой на сервер
Ubuntu 22.04/24.04
xvfb для виртуального монитора
Cron: 0 9,21 * * * cd /path/to/flip-radar-am && xvfb-run -a .venv/bin/python radar.py
Канал с сигналами
https://t.me/flipradar_am
