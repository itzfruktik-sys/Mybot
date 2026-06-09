import logging
import os
import sqlite3
import asyncio
import random
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(level=logging.INFO)

# --- ЖЕЛЕЗОБЕТОННЫЙ СЕРВЕР ДЛЯ RENDER ---
# Запускается мгновенно в отдельном потоке
def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    class DummyHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot is alive!")
        def log_message(self, format, *args):
            pass # Отключаем лишний спам в логи
    httpd = HTTPServer(('0.0.0.0', port), DummyHandler)
    httpd.serve_forever()

threading.Thread(target=run_dummy_server, daemon=True).start()
# ----------------------------------------

BOT_TOKEN = "8801581018:AAFHJOTUbwyA4j6TtxNpKCnUwl9hwHp7NY8"
ADMIN_ID = 7987342590
REQUESTS_CHAT_ID = -1003882863172
REWARD = 0.25
REFERRAL_REWARD = 2.0  
AUTO_REF_PRICE = 10.0 
STICKER_PROMO = "CAACAgIAAxkBAAERW9RqJwjNKVRcjbj9Sdk7ja_8TMzjDAACLFEAAucRQUmOOfnyXaFCbTsE"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- БАЗА ДАННЫХ ---
# Теперь, если база тупит, Render нас не убьёт
DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL:
    import psycopg2
    conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    AUTOINCREMENT_KEY = "SERIAL PRIMARY KEY"
    REAL_KEY = "NUMERIC DEFAULT 0.0"
    TEXT_KEY = "TEXT"
else:
    conn = sqlite3.connect("bot_database.db", check_same_thread=False)
    AUTOINCREMENT_KEY = "INTEGER PRIMARY KEY AUTOINCREMENT"
    REAL_KEY = "REAL DEFAULT 0.0"
    TEXT_KEY = "TEXT"

cursor = conn.cursor()
cursor.execute(f"CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, balance {REAL_KEY}, username {TEXT_KEY}, last_bonus {TEXT_KEY}, referrer_id BIGINT)")
cursor.execute(f"CREATE TABLE IF NOT EXISTS channels (channel_username {TEXT_KEY} PRIMARY KEY, invite_link {TEXT_KEY}, title {TEXT_KEY})")
cursor.execute(f"CREATE TABLE IF NOT EXISTS completed_tasks (user_id BIGINT, channel_username {TEXT_KEY}, PRIMARY KEY (user_id, channel_username))")
cursor.execute(f"CREATE TABLE IF NOT EXISTS auto_ref_queue (id {AUTOINCREMENT_KEY}, buyer_id BIGINT)")
conn.commit()

# --- КЛАВИАТУРА МЕНЮ ---
def get_main_menu():
    builder = ReplyKeyboardBuilder()
    builder.button(text="🎯 Заработать")
    builder.button(text="💰 Баланс")
    builder.button(text="🎰 Игры")
    builder.button(text="🏪 Магазин") 
    builder.button(text="💳 Вывод")
    builder.adjust(2, 2, 1)
    return builder.as_markup(resize_keyboard=True)

# --- ЛОГИКА БОТА ---
@dp.message(Command("start"))
async def start(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    username = message.from_user.username or f"id{user_id}"
    cursor.execute("SELECT user_id FROM users WHERE user_id = %s" if DATABASE_URL else "SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    user_exists = cursor.fetchone()
    
    if not user_exists:
        referrer_id = None
        if command.args and command.args.isdigit():
            possible_referrer = int(command.args)
            if possible_referrer != user_id:  
                referrer_id = possible_referrer
                
        if not referrer_id:
            cursor.execute("SELECT id, buyer_id FROM auto_ref_queue ORDER BY id ASC LIMIT 1")
            queue_item = cursor.fetchone()
            if queue_item:
                queue_row_id, buyer_id = queue_item
                referrer_id = buyer_id
                cursor.execute("DELETE FROM auto_ref_queue WHERE id = %s" if DATABASE_URL else "DELETE FROM auto_ref_queue WHERE id = ?", (queue_row_id,))
                conn.commit()

        cursor.execute("INSERT INTO users (user_id, balance, username, referrer_id) VALUES (%s, 0.0, %s, %s)" if DATABASE_URL else "INSERT INTO users (user_id, balance, username, referrer_id) VALUES (?, 0.0, ?, ?)", (user_id, username, referrer_id))
        conn.commit()
        
        if referrer_id:
            cursor.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s" if DATABASE_URL else "UPDATE users SET balance = balance + ? WHERE user_id = ?", (REFERRAL_REWARD, referrer_id))
            conn.commit()
            try:
                await bot.send_message(chat_id=referrer_id, text=f"👥 **Система Рефералов!**\nК тебе привязан новый реферал: @{username}.\nНачислено: **{REFERRAL_REWARD} ⭐**", parse_mode="Markdown")
            except Exception: pass
    else:
        cursor.execute("UPDATE users SET username = %s WHERE user_id = %s" if DATABASE_URL else "UPDATE users SET username = ? WHERE user_id = ?", (username, user_id))
        conn.commit()
    await message.answer("Привет! Выбирай действие в меню:", reply_markup=get_main_menu())

@dp.message(F.text == "🏪 Магазин")
async def store_menu(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.button(text="🛒 Купить Авто-Реферала (10 ⭐)", callback_data="buy_auto_ref")
    await message.answer("🏪 **Магазин Бота**\n\n🔥 **Товар: Авто-Реферал**\n• Стоимость: **10 ⭐**\n• Описание: Следующий свободный юзер станет твоим рефералом!", reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data == "buy_auto_ref")
async def process_buy_ref(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    cursor.execute("SELECT balance FROM users WHERE user_id = %s" if DATABASE_URL else "SELECT balance FROM users WHERE user_id = ?", (user_id,))
    balance = cursor.fetchone()[0]
    if balance < AUTO_REF_PRICE:
        await callback.answer("❌ Недостаточно звёзд! Нужно 10 ⭐", show_alert=True)
        return
    cursor.execute("UPDATE users SET balance = balance - %s WHERE user_id = %s" if DATABASE_URL else "UPDATE users SET balance = balance - ? WHERE user_id = ?", (AUTO_REF_PRICE, user_id))
    cursor.execute("INSERT INTO auto_ref_queue (buyer_id) VALUES (%s)" if DATABASE_URL else "INSERT INTO auto_ref_queue (buyer_id) VALUES (?)", (user_id,))
    conn.commit()
    await callback.message.edit_text("✅ **Успешно куплено!** Вы в очереди распределения.", parse_mode="Markdown")

@dp.message(F.text == "🎰 Игры")
async def games_menu(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.button(text="🎰 Слоты (3 ⭐)", callback_data="play_slots")
    builder.button(text="🎯 Дартс (3 ⭐)", callback_data="play_darts")
    builder.button(text="🎳 Боулинг (3 ⭐)", callback_data="play_bowling")
    builder.button(text="📦 Открыть Кейс (3 ⭐)", callback_data="open_case")
    builder.button(text="🏆 Топ игроков", callback_data="show_top")
    builder.adjust(2, 2, 1)
    await message.answer("🎮 **Игровой Клуб! Все игры по 3 ⭐**", reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data == "open_case")
async def open_case_logic(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    cursor.execute("SELECT balance FROM users WHERE user_id = %s" if DATABASE_URL else "SELECT balance FROM users WHERE user_id = ?", (user_id,))
    balance = cursor.fetchone()[0]
    if balance < 3:
        await callback.answer("❌ У тебя меньше 3 звёзд!", show_alert=True)
        return
    cursor.execute("UPDATE users SET balance = balance - 3 WHERE user_id = %s" if DATABASE_URL else "UPDATE users SET balance = balance - 3 WHERE user_id = ?", (user_id,))
    await callback.message.edit_text("📦 *Открываем секретный кейс...*", parse_mode="Markdown")
    await asyncio.sleep(1.5)
    loot = [0.0, 0.5, 1.5, 4.0, 6.0, 10.0, 15.0]
    weights = [25, 20, 20, 20, 10, 4, 1] 
    win_amount = random.choices(loot, weights=weights)[0]
    cursor.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s" if DATABASE_URL else "UPDATE users SET balance = balance + ? WHERE user_id = ?", (win_amount, user_id))
    conn.commit()
    cursor.execute("SELECT balance FROM users WHERE user_id = %s" if DATABASE_URL else "SELECT balance FROM users WHERE user_id = ?", (user_id,))
    new_balance = cursor.fetchone()[0]
    txt = f"🔥 **ОКУП: {win_amount} ⭐!**" if win_amount > 3 else "😢 Пусто..." if win_amount == 0 else f"Выпало: {win_amount} ⭐"
    await callback.message.answer(f"{txt}\n👤 Баланс: **{round(new_balance, 2)} ⭐**", reply_markup=get_main_menu(), parse_mode="Markdown")

@dp.callback_query(F.data == "play_darts")
async def play_darts(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    cursor.execute("SELECT balance FROM users WHERE user_id = %s" if DATABASE_URL else "SELECT balance FROM users WHERE user_id = ?", (user_id,))
    if cursor.fetchone()[0] < 3: return
    cursor.execute("UPDATE users SET balance = balance - 3 WHERE user_id = %s" if DATABASE_URL else "UPDATE users SET balance = balance - 3 WHERE user_id = ?", (user_id,))
    conn.commit()
    await callback.message.delete()
    dice_msg = await bot.send_dice(chat_id=user_id, emoji="🎯")
    await asyncio.sleep(2.0)
    if dice_msg.dice.value == 6:
        cursor.execute("UPDATE users SET balance = balance + 6 WHERE user_id = %s" if DATABASE_URL else "UPDATE users SET balance = balance + 6 WHERE user_id = ?", (user_id,))
    conn.commit()
    cursor.execute("SELECT balance FROM users WHERE user_id = %s" if DATABASE_URL else "SELECT balance FROM users WHERE user_id = ?", (user_id,))
    new_balance = cursor.fetchone()[0]
    txt = "🎯 **ЯБЛОЧКО! +6 ⭐**" if dice_msg.dice.value == 6 else "😢 **Мимо центра!**"
    await bot.send_message(chat_id=user_id, text=f"{txt}\n👤 Баланс: **{round(new_balance, 2)} ⭐**", reply_markup=get_main_menu(), parse_mode="Markdown")

@dp.callback_query(F.data == "play_bowling")
async def play_bowling(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    cursor.execute("SELECT balance FROM users WHERE user_id = %s" if DATABASE_URL else "SELECT balance FROM users WHERE user_id = ?", (user_id,))
    if cursor.fetchone()[0] < 3: return
    cursor.execute("UPDATE users SET balance = balance - 3 WHERE user_id = %s" if DATABASE_URL else "UPDATE users SET balance = balance - 3 WHERE user_id = ?", (user_id,))
    conn.commit()
    await callback.message.delete()
    dice_msg = await bot.send_dice(chat_id=user_id, emoji="🎳")
    await asyncio.sleep(2.0)
    if dice_msg.dice.value == 6:
        cursor.execute("UPDATE users SET balance = balance + 6 WHERE user_id = %s" if DATABASE_URL else "UPDATE users SET balance = balance + 6 WHERE user_id = ?", (user_id,))
    conn.commit()
    cursor.execute("SELECT balance FROM users WHERE user_id = %s" if DATABASE_URL else "SELECT balance FROM users WHERE user_id = ?", (user_id,))
    new_balance = cursor.fetchone()[0]
    txt = "🎳 **СТРАЙК! +6 ⭐**" if dice_msg.dice.value == 6 else "😢 **Не страйк!**"
    await bot.send_message(chat_id=user_id, text=f"{txt}\n👤 Баланс: **{round(new_balance, 2)} ⭐**", reply_markup=get_main_menu(), parse_mode="Markdown")

@dp.callback_query(F.data == "play_slots")
async def play_slots_logic(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    cursor.execute("SELECT balance FROM users WHERE user_id = %s" if DATABASE_URL else "SELECT balance FROM users WHERE user_id = ?", (user_id,))
    if cursor.fetchone()[0] < 3: return
    cursor.execute("UPDATE users SET balance = balance - 3 WHERE user_id = %s" if DATABASE_URL else "UPDATE users SET balance = balance - 3 WHERE user_id = ?", (user_id,))
    conn.commit()
    await callback.message.delete()
    dice_msg = await bot.send_dice(chat_id=user_id, emoji="🎰")
    win_values = [1, 22, 43, 64, 2, 3, 4, 5, 6, 7, 8, 9, 10, 16, 17, 18, 32, 33, 34, 48, 49, 50] 
    await asyncio.sleep(2.5)
    if dice_msg.dice.value in win_values:
        cursor.execute("UPDATE users SET balance = balance + 6 WHERE user_id = %s" if DATABASE_URL else "UPDATE users SET balance = balance + 6 WHERE user_id = ?", (user_id,))
        conn.commit()
        await bot.send_message(chat_id=user_id, text="🎉 **ПОБЕДА! +6 ⭐**", reply_markup=get_main_menu(), parse_mode="Markdown")
    else:
        await bot.send_message(chat_id=user_id, text="😢 Не повезло...", reply_markup=get_main_menu())

@dp.callback_query(F.data == "show_top")
async def show_top_players(callback: types.CallbackQuery):
    cursor.execute("SELECT username, balance FROM users ORDER BY balance DESC LIMIT 10")
    leaders = cursor.fetchall()
    top_text = "🏆 **ТОП-10 ИГРОКОВ** 🏆\n\n"
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    for i, leader in enumerate(leaders):
        top_text += f"{medals[i]} @{leader[0] or 'Аноним'} — **{round(leader[1], 2)} ⭐**\n"
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад", callback_data="back_to_games")
    await callback.message.edit_text(top_text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data == "back_to_games")
async def back_games(callback: types.CallbackQuery):
    await callback.message.delete()
    await games_menu(callback.message)

@dp.message(F.text == "🎯 Заработать")
async def earn(message: types.Message):
    user_id = message.from_user.id
    cursor.execute("SELECT channel_username, invite_link, title FROM channels WHERE channel_username NOT IN (SELECT channel_username FROM completed_tasks WHERE user_id = %s) LIMIT 1" if DATABASE_URL else "SELECT channel_username, invite_link, title FROM channels WHERE channel_username NOT IN (SELECT channel_username FROM completed_tasks WHERE user_id = ?) LIMIT 1", (user_id,))
    channel = cursor.fetchone()
    if not channel:
        await message.answer("Пока нет заданий.")
        return
    builder = InlineKeyboardBuilder()
    builder.button(text=f"Перейти", url=channel[1])
    builder.button(text="✅ Проверить", callback_data=f"check_{channel[0]}")
    await message.answer(f"Подпишись на {channel[2]}:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("check_"))
async def check(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    channel = callback.data.split("_")[1]
    cursor.execute("SELECT 1 FROM completed_tasks WHERE user_id = %s AND channel_username = %s" if DATABASE_URL else "SELECT 1 FROM completed_tasks WHERE user_id = ? AND channel_username = ?", (user_id, channel))
    if cursor.fetchone(): return
    cursor.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s" if DATABASE_URL else "UPDATE users SET balance = balance + ? WHERE user_id = ?", (REWARD, user_id))
    cursor.execute("INSERT INTO completed_tasks VALUES (%s, %s)" if DATABASE_URL else "INSERT OR IGNORE INTO completed_tasks VALUES (?, ?)", (user_id, channel))
    conn.commit()
    await callback.message.edit_text("🎉 Награда зачислена!")

@dp.message(F.text == "💰 Баланс")
async def check_balance(message: types.Message):
    user_id = message.from_user.id
    cursor.execute("SELECT balance FROM users WHERE user_id = %s" if DATABASE_URL else "SELECT balance FROM users WHERE user_id = ?", (user_id,))
    current_balance = cursor.fetchone()[0]
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user_id}"
    await message.answer(f"💰 Баланс: **{round(current_balance, 2)} ⭐**\n🔗 Реф. ссылка:\n`{ref_link}`", parse_mode="Markdown")

@dp.message(F.text == "💳 Вывод")
async def withdraw_menu(message: types.Message):
    builder = InlineKeyboardBuilder()
    for amount in [15, 25, 40, 50, 100]: builder.button(text=f"{amount} ⭐", callback_data=f"withdraw_{amount}")
    builder.adjust(2)
    await message.answer("Сумма вывода:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("withdraw_"))
async def process_withdraw(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    amount = int(callback.data.split("_")[1])
    cursor.execute("SELECT balance FROM users WHERE user_id = %s" if DATABASE_URL else "SELECT balance FROM users WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    if not res or res[0] < amount: return
    cursor.execute("UPDATE users SET balance = balance - %s WHERE user_id = %s" if DATABASE_URL else "UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    await callback.message.edit_text("✅ Заявка создана!")
    await bot.send_message(chat_id=REQUESTS_CHAT_ID, text=f"🔔 Заявка: {amount} ⭐ от @{callback.from_user.username}")

async def send_scheduled_sticker():
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    for user in users:
        try: await bot.send_sticker(chat_id=user[0], sticker=STICKER_PROMO)
        except Exception: pass

async def main():
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(send_scheduled_sticker, "interval", hours=2)
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
