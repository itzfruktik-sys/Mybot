import logging
import sqlite3
import asyncio
import random
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

# Модуль для отправки сообщений каждые 2 часа
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(level=logging.INFO)

# НАСТРОЙКИ
BOT_TOKEN = "8801581018:AAFHJOTUbwyA4j6TtxNpKCnUwl9hwHp7NY8"
ADMIN_ID = 7987342590
REQUESTS_CHAT_ID = -1003882863172
REWARD = 0.25
REFERRAL_REWARD = 2.0  
DAILY_BONUS_REWARD = 1.0  
AUTO_REF_PRICE = 10.0 

# 🎰 ТВОЙ СТИКЕР ДЛЯ РАССЫЛКИ (Каждые 2 часа)
STICKER_PROMO = "CAACAgIAAxkBAAERW9RqJwjNKVRcjbj9Sdk7ja_8TMzjDAACLFEAAucRQUmOOfnyXaFCbTsE"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# БАЗА ДАННЫХ
conn = sqlite3.connect("bot_database.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, balance REAL DEFAULT 0.0, username TEXT, last_bonus TEXT, referrer_id INTEGER)")
cursor.execute("CREATE TABLE IF NOT EXISTS channels (channel_username TEXT PRIMARY KEY, invite_link TEXT, title TEXT)")
cursor.execute("CREATE TABLE IF NOT EXISTS completed_tasks (user_id INTEGER, channel_username TEXT, PRIMARY KEY (user_id, channel_username))")
cursor.execute("CREATE TABLE IF NOT EXISTS auto_ref_queue (id INTEGER PRIMARY KEY AUTOINCREMENT, buyer_id INTEGER)")
conn.commit()

try:
    cursor.execute("ALTER TABLE users ADD COLUMN username TEXT")
    cursor.execute("ALTER TABLE users ADD COLUMN last_bonus TEXT")
    cursor.execute("ALTER TABLE users ADD COLUMN referrer_id INTEGER")
    conn.commit()
except sqlite3.OperationalError:
    pass  

def get_main_menu():
    builder = ReplyKeyboardBuilder()
    builder.button(text="🎯 Заработать")
    builder.button(text="🎁 Бонус")
    builder.button(text="💰 Баланс")
    builder.button(text="🎰 Игры")
    builder.button(text="🏪 Магазин") 
    builder.button(text="💳 Вывод")
    builder.adjust(2, 2, 2)
    return builder.as_markup(resize_keyboard=True)

@dp.message(Command("start"))
async def start(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    username = message.from_user.username or f"id{user_id}"
    
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
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
                cursor.execute("DELETE FROM auto_ref_queue WHERE id = ?", (queue_row_id,))
                conn.commit()

        cursor.execute("INSERT INTO users (user_id, balance, username, referrer_id) VALUES (?, 0.0, ?, ?)", (user_id, username, referrer_id))
        conn.commit()
        
        if referrer_id:
            cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (REFERRAL_REWARD, referrer_id))
            conn.commit()
            try:
                await bot.send_message(
                    chat_id=referrer_id, 
                    text=f"👥 **Система Рефералов!**\nК тебе привязан новый реферал: @{username}.\nНачислено: **{REFERRAL_REWARD} ⭐**"
                )
            except Exception:
                pass
    else:
        cursor.execute("UPDATE users SET username = ? WHERE user_id = ?", (username, user_id))
        conn.commit()
        
    await message.answer("Привет! Выбирай действие в меню:", reply_markup=get_main_menu())

# 🎁 ЕЖЕДНЕВНЫЙ БОНУС
@dp.message(F.text == "🎁 Бонус")
async def get_daily_bonus(message: types.Message):
    user_id = message.from_user.id
    cursor.execute("SELECT last_bonus FROM users WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    now = datetime.utcnow()
    
    if res and res[0]:
        last_bonus_time = datetime.fromisoformat(res[0])
        if now - last_bonus_time < timedelta(hours=24):
            time_left = timedelta(hours=24) - (now - last_bonus_time)
            hours, remainder = divmod(int(time_left.total_seconds()), 3600)
            minutes, _ = divmod(remainder, 60)
            await message.answer(f"❌ Вы уже забирали бонус!\n⏳ Новый бонус через: **{hours}ч. {minutes}мин.**", parse_mode="Markdown")
            return
            
    cursor.execute("UPDATE users SET balance = balance + ?, last_bonus = ? WHERE user_id = ?", (DAILY_BONUS_REWARD, now.isoformat(), user_id))
    conn.commit()
    await message.answer(f"🎁 **Бонус получен!**\n💰 Зачислено: **{DAILY_BONUS_REWARD} ⭐**")

# 🏪 МАГАЗИН
@dp.message(F.text == "🏪 Магазин")
async def store_menu(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.button(text="🛒 Купить Авто-Реферала (10 ⭐)", callback_data="buy_auto_ref")
    await message.answer(
        "🏪 **Магазин Бота**\n\n"
        "🔥 **Товар: Авто-Реферал**\n"
        "• Стоимость: **10 ⭐**\n"
        "• Описание: Ты встаешь в специальную систему распределения. Следующий новый пользователь, который зайдет в бота без приглашения, **автоматически станет твоим рефералом** и принесет тебе **2 ⭐**!",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data == "buy_auto_ref")
async def process_buy_ref(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    balance = cursor.fetchone()[0]
    
    if balance < AUTO_REF_PRICE:
        await callback.answer("❌ Недостаточно звёзд! Нужно 10 ⭐", show_alert=True)
        return
        
    cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (AUTO_REF_PRICE, user_id))
    cursor.execute("INSERT INTO auto_ref_queue (buyer_id) VALUES (?)", (user_id,))
    conn.commit()
    
    await callback.message.edit_text("✅ **Успешно куплено!**\nВы добавлены в очередь распределения. Как только зайдет новый пользователь, он станет вашим рефералом!")

# 🎰 МЕНЮ ИГРЫ
@dp.message(F.text == "🎰 Игры")
async def games_menu(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.button(text="🎰 Слоты (3 ⭐)", callback_data="play_slots")
    builder.button(text="🎯 Дартс (3 ⭐)", callback_data="play_darts")
    builder.button(text="🎳 Боулинг (3 ⭐)", callback_data="play_bowling")
    builder.button(text="📦 Открыть Кейс (3 ⭐)", callback_data="open_case")
    builder.button(text="🏆 Топ игроков", callback_data="show_top")
    builder.adjust(2, 2, 1)
    await message.answer(
        "🎮 **Игровой Клуб! Выбирай во что сыграть:**\n\n"
        "• Все игры и кейсы стоят фиксировано — **3 ⭐**\n"
        "• При выигрыше ты удваиваешь ставку и получаешь **6 ⭐**!",
        reply_markup=builder.as_markup()
    )

# 📦 ЛОГИКА КЕЙСОВ
@dp.callback_query(F.data == "open_case")
async def open_case_logic(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    balance = cursor.fetchone()[0]
    
    if balance < 3:
        await callback.answer("❌ У тебя меньше 3 звёзд!", show_alert=True)
        return
        
    cursor.execute("UPDATE users SET balance = balance - 3 WHERE user_id = ?", (user_id,))
    
    await callback.message.edit_text("📦 *Открываем секретный кейс...*")
    await asyncio.sleep(1.5)
    
    loot = [0.0, 0.5, 1.5, 4.0, 6.0, 10.0, 15.0]
    weights = [25, 20, 20, 20, 10, 4, 1] 
    win_amount = random.choices(loot, weights=weights)[0]
    
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (win_amount, user_id))
    conn.commit()
    
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    new_balance = cursor.fetchone()[0]
    
    if win_amount > 3:
        txt = f"🔥 **ОКУП! Выпал супер-приз: {win_amount} ⭐!**"
    elif win_amount == 0:
        txt = "😢 К сожалению, кейс оказался пустым..."
    else:
        txt = f"Выпало: {win_amount} ⭐"
        
    await callback.message.answer(f"{txt}\n👤 Баланс: **{round(new_balance, 2)} ⭐**", reply_markup=get_main_menu())

# 🎯 ЛОГИКА ДАРТСА (СТРОГО 6 — ЯБЛОЧКО)
@dp.callback_query(F.data == "play_darts")
async def play_darts(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    if cursor.fetchone()[0] < 3:
        await callback.answer("❌ Нужно 3 ⭐!", show_alert=True)
        return
    cursor.execute("UPDATE users SET balance = balance - 3 WHERE user_id = ?", (user_id,))
    conn.commit()
    await callback.message.delete()
    
    dice_msg = await bot.send_dice(chat_id=user_id, emoji="🎯")
    await asyncio.sleep(2.0)
    
    # Ровно 6 — это самый центр мишени (красное яблочко)
    if dice_msg.dice.value == 6:
        cursor.execute("UPDATE users SET balance = balance + 6 WHERE user_id = ?", (user_id,))
        conn.commit()
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        new_balance = cursor.fetchone()[0]
        await bot.send_message(chat_id=user_id, text=f"🎯 **ПРЯМО В ЯБЛОЧКО! Идеальное попадание!**\nВыигрыш: **6 ⭐** зачислены.\n👤 Баланс: **{round(new_balance, 2)} ⭐**", reply_markup=get_main_menu())
    else:
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        new_balance = cursor.fetchone()[0]
        await bot.send_message(chat_id=user_id, text=f"😢 **Мимо центра!** Стрела попала в боковое кольцо.\nСтавка списана.\n👤 Баланс: **{round(new_balance, 2)} ⭐**", reply_markup=get_main_menu())

# 🎳 ЛОГИКА БОУЛИНГА (СТРОГО 6 — СТРАЙК)
@dp.callback_query(F.data == "play_bowling")
async def play_bowling(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    if cursor.fetchone()[0] < 3:
        await callback.answer("❌ Нужно 3 ⭐!", show_alert=True)
        return
    cursor.execute("UPDATE users SET balance = balance - 3 WHERE user_id = ?", (user_id,))
    conn.commit()
    await callback.message.delete()
    
    dice_msg = await bot.send_dice(chat_id=user_id, emoji="🎳")
    await asyncio.sleep(2.0)
    
    # В боулинге только 6 — это полный СТРАЙК (сбиты все кегли)
    if dice_msg.dice.value == 6:
        cursor.execute("UPDATE users SET balance = balance + 6 WHERE user_id = ?", (user_id,))
        conn.commit()
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        new_balance = cursor.fetchone()[0]
        await bot.send_message(chat_id=user_id, text=f"🎳 **СТРАЙК! Все кегли разлетелись в щепки!**\nВыигрыш: **6 ⭐** зачислены.\n👤 Баланс: **{round(new_balance, 2)} ⭐**", reply_markup=get_main_menu())
    else:
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        new_balance = cursor.fetchone()[0]
        await bot.send_message(chat_id=user_id, text=f"😢 **Не страйк!** Несколько кеглей осталось стоять.\nСтавка списана.\n👤 Баланс: **{round(new_balance, 2)} ⭐**", reply_markup=get_main_menu())

# ЛОГИКА СЛОТА
@dp.callback_query(F.data == "play_slots")
async def play_slots_logic(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    if cursor.fetchone()[0] < 3:
        await callback.answer("❌ У тебя меньше 3 звёзд!", show_alert=True)
        return
    cursor.execute("UPDATE users SET balance = balance - 3 WHERE user_id = ?", (user_id,))
    conn.commit()
    await callback.message.delete()
    
    dice_msg = await bot.send_dice(chat_id=user_id, emoji="🎰")
    win_values = [1, 22, 43, 64, 2, 3, 4, 5, 6, 7, 8, 9, 10, 16, 17, 18, 32, 33, 34, 48, 49, 50] 
    await asyncio.sleep(2.5)
    
    if dice_msg.dice.value in win_values:
        cursor.execute("UPDATE users SET balance = balance + 6 WHERE user_id = ?", (user_id,))
        conn.commit()
        await bot.send_message(chat_id=user_id, text="🎉 **ПОБЕДА! Слот выдал выигрыш!**\nЗачислено: **6 ⭐**", reply_markup=get_main_menu())
    else:
        await bot.send_message(chat_id=user_id, text="😢 Не повезло, выпали разные символы...", reply_markup=get_main_menu())

# 🏆 ТОП ИГРОКОВ
@dp.callback_query(F.data == "show_top")
async def show_top_players(callback: types.CallbackQuery):
    cursor.execute("SELECT username, balance FROM users ORDER BY balance DESC LIMIT 10")
    leaders = cursor.fetchall()
    top_text = "🏆 **ТОП-10 САМЫХ БОГАТЫХ ИГРОКОВ** 🏆\n\n"
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    for i, leader in enumerate(leaders):
        top_text += f"{medals[i]} @{leader[0] or 'Аноним'} — **{round(leader[1], 2)} ⭐**\n"
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад в Игры", callback_data="back_to_games")
    await callback.message.edit_text(top_text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data == "back_to_games")
async def back_games(callback: types.CallbackQuery):
    await callback.message.delete()
    await games_menu(callback.message)

# 🎯 КНОПКА ЗАРАБОТАТЬ
@dp.message(F.text == "🎯 Заработать")
async def earn(message: types.Message):
    user_id = message.from_user.id
    cursor.execute("SELECT channel_username, invite_link, title FROM channels WHERE channel_username NOT IN (SELECT channel_username FROM completed_tasks WHERE user_id = ?) LIMIT 1", (user_id,))
    channel = cursor.fetchone()
    if not channel:
        await message.answer("Пока нет заданий.")
        return
    try:
        builder = InlineKeyboardBuilder()
        builder.button(text=f"Перейти в {channel[2]}", url=channel[1])
        builder.button(text="✅ Проверить", callback_data=f"check_{channel[0]}")
        await message.answer("Выполни задание:", reply_markup=builder.as_markup())
    except Exception:
        await message.answer("⚠️ Ошибка ссылки задания. Используй /fix_db для очистки мусора!")

@dp.callback_query(F.data.startswith("check_"))
async def check(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    channel = callback.data.split("_")[1]
    cursor.execute("SELECT 1 FROM completed_tasks WHERE user_id = ? AND channel_username = ?", (user_id, channel))
    if cursor.fetchone():
        await callback.answer("Вы уже получили награду!", show_alert=True)
        return
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (REWARD, user_id))
    cursor.execute("INSERT OR IGNORE INTO completed_tasks VALUES (?, ?)", (user_id, channel))
    conn.commit()
    await callback.message.edit_text("🎉 Задание выполнено! Звезды начислены.")

# 💰 БАЛАНС
@dp.message(F.text == "💰 Баланс")
async def check_balance(message: types.Message):
    user_id = message.from_user.id
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    current_balance = cursor.fetchone()[0]
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user_id}"
    await message.answer(f"👤 **Ваш профиль:**\n💰 Баланс: **{round(current_balance, 2)} звезд**\n\n👥 **Рефералка:**\nПриведи друга и получи **{REFERRAL_REWARD} ⭐**!\n🔗 Ссылка:\n`{ref_link}`", parse_mode="Markdown")

# АДМИН-ПАНЕЛЬ
@dp.message(Command("stats"))
async def admin_stats(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM auto_ref_queue")
    queue_len = cursor.fetchone()[0]
    await message.answer(f"📊 **СТАТИСТИКА БОТА:**\n\n👤 Всего пользователей: **{total_users}**\n🏪 Очередь на авто-рефов: **{queue_len} чел.**")

@dp.message(Command("send"))
async def admin_broadcast(message: types.Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID: return
    if not command.args:
        await message.answer("❌ Напиши текст рассылки!", parse_mode="Markdown")
        return
    broadcast_text = command.args
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    count = 0
    await message.answer("⏳ Рассылка запущена...")
    for user in users:
        try:
            await bot.send_message(chat_id=user[0], text=broadcast_text)
            count += 1
            await asyncio.sleep(0.05) 
        except Exception:
            pass
    await message.answer(f"✅ Успешно! Сообщение получили **{count}** пользователей.")

@dp.message(Command("add_channel"))
async def add_ch(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    p = message.text.split(maxsplit=3)
    if len(p) < 4: return
    cursor.execute("INSERT OR REPLACE INTO channels VALUES (?, ?, ?)", (p[1], p[2], p[3]))
    conn.commit()
    await message.answer("✅ Добавлено!")

@dp.message(Command("del_channel"))
async def del_ch(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    if len(message.text.split()) < 2: return
    cursor.execute("DELETE FROM channels WHERE channel_username = ?", (message.text.split()[1],))
    conn.commit()
    await message.answer("✅ Удалено!")

@dp.message(Command("fix_db"))
async def fix_database(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    cursor.execute("DELETE FROM channels WHERE invite_link NOT LIKE 'http%'")
    conn.commit()
    await message.answer("✅ База очищена от мусора!")

# ВЫВОД СРЕДСТВ
@dp.message(F.text == "💳 Вывод")
async def withdraw_menu(message: types.Message):
    builder = InlineKeyboardBuilder()
    for amount in [15, 25, 40, 50, 100]:
        builder.button(text=f"{amount} ⭐", callback_data=f"withdraw_{amount}")
    builder.adjust(2)
    await message.answer("Выберите сумму для вывода:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("withdraw_"))
async def process_withdraw(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    amount = int(callback.data.split("_")[1])
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    if not res or res[0] < amount:
        await callback.answer("❌ Недостаточно звёзд!", show_alert=True)
        return
    cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    await callback.message.edit_text("✅ Заявка создана!")
    await bot.send_message(chat_id=REQUESTS_CHAT_ID, text=f"🔔 Заявка: {amount} ⭐ от @{callback.from_user.username}")

async def send_scheduled_sticker():
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    for user in users:
        try:
            await bot.send_sticker(chat_id=user[0], sticker=STICKER_PROMO)
            await bot.send_message(chat_id=user[0], text="🎰 Испытай удачу в казино прямо сейчас! Нажми кнопку «Игры»!")
        except Exception:
            pass

async def main():
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(send_scheduled_sticker, "interval", hours=2)
    scheduler.start()
    print("Бот успешно запущен и готов к работе!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
