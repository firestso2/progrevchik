import asyncio
import logging
import random
import aiosqlite
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# --- КОНФИГУРАЦИЯ ---
TOKEN = "8538009406:AAGuBhEHnRy6ImL0gwV8bxJVG_4IpeAKKbg"  # Вставьте ваш токен
ADMIN_ID = 8416449434       # ВАЖНО: ЗАМЕНИТЕ НА ВАШ ID (число)

# Начальный список каналов для прогрева
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

# --- РАБОТА С БАЗОЙ ДАННЫХ ---

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                chat_id INTEGER PRIMARY KEY,
                active INTEGER DEFAULT 1,
                title TEXT
            )
        """)
        # Добавляем начальные каналы, если их нет
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
        logging.warning(f"Канал {chat_id} деактивирован (бот кикнут или нет прав).")

# --- ЛОГИКА ОТПРАВКИ ---

async def send_publication(post_number):
    """Отправляет конкретный номер публикации во все активные каналы"""
    channels = await get_active_channels()
    text = f"Публикация {post_number}"
    
    logging.info(f"--- НАЧАЛО РАССЫЛКИ: {text} ---")
    
    for chat_id in channels:
        try:
            await bot.send_message(chat_id=chat_id, text=text)
            # Важно: пауза между каналами, чтобы не словить FloodWait при массовой отправке
            await asyncio.sleep(random.uniform(1.0, 3.0)) 
        except Exception as e:
            logging.error(f"Не удалось отправить в {chat_id}: {e}")
            # Если ошибка критическая (бот заблокирован, кикнут), убираем канал из базы
            if "Forbidden" in str(e) or "chat not found" in str(e).lower():
                await deactivate_channel(chat_id)
    
    logging.info(f"--- КОНЕЦ РАССЫЛКИ: {text} ---")

# --- ПЛАНИРОВЩИК (РАНДОМАЙЗЕР) ---

def schedule_jobs_for_today():
    """Генерирует 5 случайных временных меток на сегодня и ставит задачи"""
    now = datetime.now()
    
    # Очищаем старые задачи на отправку (оставляем только задачу планирования)
    for job in scheduler.get_jobs():
        if job.id.startswith("post_"):
            job.remove()

    # Генерируем 5 случайных времен в диапазоне с 08:00 до 23:00
    # Если скрипт запущен днем, генерируем время от "сейчас" до 23:00
    
    start_hour = max(8, now.hour)
    if now.minute > 0 and start_hour == now.hour:
        start_hour += 1
    
    if start_hour >= 23:
        logging.warning("Сегодня уже поздно для рассылки, ждем завтра.")
        return

    # Создаем список всех доступных минут до конца дня
    available_minutes = []
    for h in range(start_hour, 23):
        for m in range(0, 60):
            available_minutes.append((h, m))
            
    if len(available_minutes) < 5:
        logging.warning("Слишком мало времени до конца дня для 5 постов.")
        selected_times = available_minutes # Берем что есть
    else:
        # Выбираем 5 случайных точек во времени и сортируем их
        selected_times = sorted(random.sample(available_minutes, 5))

    logging.info(f"План публикаций на сегодня ({len(selected_times)} шт):")
    
    for i, (h, m) in enumerate(selected_times, start=1):
        run_date = now.replace(hour=h, minute=m, second=0, microsecond=0)
        job_id = f"post_{i}"
        
        # Планируем задачу
        scheduler.add_job(
            send_publication, 
            'date', 
            run_date=run_date, 
            args=[i], 
            id=job_id
        )
        logging.info(f"  [{i}] запланировано на {run_date.strftime('%H:%M')}")

# Эта функция будет запускаться каждую ночь в 00:05, чтобы составить план на новый день
async def daily_reschedule():
    logging.info("Новый день! Генерирую новое случайное расписание...")
    schedule_jobs_for_today()

# --- АДМИН ПАНЕЛЬ ---

@dp.message(Command("status"))
async def cmd_status(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    
    channels = await get_active_channels()
    jobs = scheduler.get_jobs()
    post_jobs = [j for j in jobs if j.id.startswith("post_")]
    post_jobs.sort(key=lambda x: x.next_run_time)
    
    response = [f"📊 **Статус бота**"]
    response.append(f"Активных каналов: {len(channels)}")
    response.append(f"Запланировано постов на сегодня: {len(post_jobs)}")
    
    for job in post_jobs:
        msk_time = job.next_run_time.strftime('%H:%M')
        response.append(f"🕒 {msk_time} — {job.args[0]}-я публикация")
        
    await message.answer("\n".join(response), parse_mode="Markdown")

@dp.message(Command("force_post"))
async def cmd_force_post(message: types.Message):
    """Принудительно отправить пост прямо сейчас. Пример: /force_post 1"""
    if message.from_user.id != ADMIN_ID: return
    try:
        args = message.text.split()
        num = int(args[1]) if len(args) > 1 else 1
        await message.answer(f"🚀 Запускаю принудительную рассылку №{num}...")
        await send_publication(num)
        await message.answer("✅ Рассылка завершена.")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")

@dp.message(Command("regenerate"))
async def cmd_regenerate(message: types.Message):
    """Пересоздать расписание на сегодня"""
    if message.from_user.id != ADMIN_ID: return
    schedule_jobs_for_today()
    await message.answer("🔄 Расписание на сегодня пересоздано случайным образом. Проверь /status")

# --- ЗАПУСК ---

async def main():
    await init_db()
    
    # 1. Запускаем планировщик
    scheduler.start()
    
    # 2. Добавляем задачу, которая будет каждое утро (00:05) обновлять график
    scheduler.add_job(daily_reschedule, 'cron', hour=0, minute=5)
    
    # 3. Генерируем график на текущий день прямо при запуске
    schedule_jobs_for_today()
    
    # Удаляем вебхуки и запускаем
    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logging.error(f"Бот упал: {e}")

if __name__ == "__main__":
    asyncio.run(main())
