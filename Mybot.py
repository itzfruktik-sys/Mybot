import logging
import os
import sqlite3
import asyncio
import random
from datetime import datetime, timedelta
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Конфиг
BOT_TOKEN = "8801581018:AAFHJOTUbwyA4j6TtxNpKCnUwl9hwHp7NY8"
DATABASE_URL = os.environ.get("DATABASE_URL")
PORT = int(os.environ.get("PORT", 8080))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER ---
async def handle(request):
    return web.Response(text="Bot is running!")

async def start_server():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logging.info(f"Web server started on port {PORT}")

# --- ЛОГИКА БОТА ---
# (Твой остальной код с кнопками и функциями...)
# Убедись, что все функции earn, withdraw и другие сохранены здесь

async def main():
    await start_server()  # Запускаем сервер перед ботом
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
    
