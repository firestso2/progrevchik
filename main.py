import asyncio
import logging
import random
import aiosqlite
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# --- КОНФИГУРАЦИЯ (ОБНОВЛЕНО) ---
TOKEN = "8538009406:AAEeDvEKhcn8oI16c-QO7QkyN3CdZZRBbUc"  # Ваш НОВЫЙ токен
ADMIN_ID = 8416449434                                   # Ваш проверенный ID

# Начальный список каналов для прогрева из вашего кода
INITIAL_CHANNELS = [
    -1003563461665, -1003595733582, -1003696903994, -1003671263610, 
    -1003543850773, -1003396466024, -1003638323492, -1003544426070, 
    -1003628833432, -1003596090401
]

DB_NAME = "channels.db"

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

bot = Bot(token=TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()

# --- СИСТЕМА УВЕДОМЛЕНИЙ АДМИНА ---

async def send_admin_report(text):
    """Отправляет отчет вам в личные сообщения"""
    try:
        await bot.send_message(ADMIN_ID, f"🤖 **ОТЧЕТ ПРОГРЕВА**\n{text}", parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Не удалось отправить отчет админу: {e}")

# --- РАБОТА С БАЗОЙ ДАННЫХ (Полная версия) ---

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                chat_id INTEGER PRIMARY KEY,
                active INTEGER DEFAULT 1,
                title TEXT
            )
        """)
        for chat_id in INITIAL_CHANNELS:
            try:
                await db.execute("INSERT OR IGNORE INTO channels (chat_id) VALUES (?)", (chat_id,))
            except Exception as e:
                logging.error(f"Ошибка добавления {chat_id}: {e}")
        await db.commit()

async def get_active_channels():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT chat_id FROM channels WHERE active = 1") as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

async def deactivate_channel(chat_id):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE channels SET active = 0 WHERE chat_id = ?", (chat_id,))
        await db.commit()
        logging.warning(f"Канал {chat_id} деактивирован.")
        await send_admin_report(f"⚠️ Канал `{chat_id}` удален из рассылки (нет прав).")

# --- ЛОГИКА ОТПРАВКИ (С уведомлениями) ---

async def send_publication(post_number):
    """Отправляет публикацию во все активные каналы и пишет отчет админу"""
    channels = await get_active_channels()
    text = f"Публикация {post_number}"
    success_count = 0
    
    logging.info(f"--- НАЧАЛО РАССЫЛКИ: {text} ---")
    
    for chat_id in channels:
        try:
            await bot.send_message(chat_id=chat_id, text=text)
            success_count += 1
            await asyncio.sleep(random.uniform(1.0, 3.0)) 
        except Exception as e:
            logging.error(f"Не удалось отправить в {chat_id}: {e}")
            if "Forbidden" in str(e) or "chat not found" in str(e).lower():
                await deactivate_channel(chat_id)
    
    await send_admin_report(f"✅ Рассылка №{post_number} завершена.\nУспешно отправлено: {success_count} из {len(channels)} каналов.")
    logging.info(f"--- КОНЕЦ РАССЫЛКИ: {text} ---")

# --- ПЛАНИРОВЩИК (РАНДОМАЙЗЕР) ---

def schedule_jobs_for_today():
    now = datetime.now()
    for job in scheduler.get_jobs():
        if job.id.startswith("post_"):
            job.remove()

    start_hour = max(8, now.hour)
    if now.minute > 0 and start_hour == now.hour:
        start_hour += 1
    
    if start_hour >= 23:
        logging.warning("Сегодня уже поздно для рассылки.")
        return

    available_minutes = []
    for h in range(start_hour, 23):
        for m in range(0, 60):
            available_minutes.append((h, m))
            
    if len(available_minutes) < 5:
        selected_times = available_minutes
    else:
        selected_times = sorted(random.sample(available_minutes, 5))

    for i, (h, m) in enumerate(selected_times, start=1):
        run_date = now.replace(hour=h, minute=m, second=0, microsecond=0)
        scheduler.add_job(send_publication, 'date', run_date=run_date, args=[i], id=f"post_{i}")
        logging.info(f"  [{i}] запланировано на {run_date.strftime('%H:%M')}")

async def daily_reschedule():
    logging.info("Генерирую новое расписание...")
    schedule_jobs_for_today()
    await send_admin_report("🔄 Расписание на новый день успешно сформировано!")

# --- ОБРАБОТКА КОМАНД (Полная версия) ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("🚀 Бот-прогревщик запущен и готов к работе!")
    if message.from_user.id == ADMIN_ID:
        await message.answer("Вы авторизованы как администратор.")

@dp.message(Command("status"))
async def cmd_status(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    channels = await get_active_channels()
    jobs = sorted([j for j in scheduler.get_jobs() if j.id.startswith("post_")], key=lambda x: x.next_run_time)
    
    response = [f"📊 **Статус бота**", f"Активных каналов: {len(channels)}", f"Постов на сегодня: {len(jobs)}"]
    for job in jobs:
        response.append(f"🕒 {job.next_run_time.strftime('%H:%M')} — {job.args[0]}-я публикация")
    await message.answer("\n".join(response), parse_mode="Markdown")

@dp.message(Command("force_post"))
async def cmd_force_post(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        args = message.text.split()
        num = int(args[1]) if len(args) > 1 else 1
        await message.answer(f"🚀 Запускаю принудительную рассылку №{num}...")
        await send_publication(num)
        await message.answer("✅ Принудительная рассылка завершена.")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")

@dp.message(Command("regenerate"))
async def cmd_regenerate(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    schedule_jobs_for_today()
    await message.answer("🔄 Расписание на сегодня пересоздано. Проверьте /status")

# --- ЗАПУСК ---

async def main():
    await init_db()
    
    # Сброс вебхуков для предотвращения TelegramConflictError
    await bot.delete_webhook(drop_pending_updates=True) 
    
    scheduler.start()
    scheduler.add_job(daily_reschedule, 'cron', hour=0, minute=5)
    schedule_jobs_for_today()
    
    await send_admin_report("🚀 Бот успешно запущен на сервере Bothost!")
    
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logging.error(f"Критическая ошибка: {e}")

if __name__ == "__main__":
    asyncio.run(main())
