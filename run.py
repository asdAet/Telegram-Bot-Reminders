from config import BOT_TOKEN
import sqlite3
import json
from aiogram import Bot, Dispatcher, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from datetime import datetime

import asyncio

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# FSM States
class ReminderStates(StatesGroup):
    waiting_for_reminder_time = State()


# Constants
REMINDERS_FILE = "reminders.json"

# Initialize reminders storage
reminders = {}

# Keyboards
main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="✉ Создать напоминание")],
        [KeyboardButton(text="🔎 Посмотреть все напоминания")]
    ],
    resize_keyboard=True
)


def format_reminder(reminder):
    return f"Время: {reminder['time']}\nСообщение: {reminder['message']}\nОсталось: {reminder['remaining']}"


# Database functions
def init_db():
    conn = sqlite3.connect("reminders.db")
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS reminders (
        id INTEGER PRIMARY KEY,
        user_id INTEGER,
        time TEXT,
        message TEXT
    )
    """)
    conn.commit()
    conn.close()


def save_reminder_to_db(user_id, time, message):
    conn = sqlite3.connect("reminders.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO reminders (user_id, time, message) VALUES (?, ?, ?)", (user_id, time, message))
    conn.commit()
    conn.close()


def load_reminders_from_db():
    conn = sqlite3.connect("reminders.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, time, message FROM reminders")
    reminders = cursor.fetchall()
    conn.close()
    return reminders


def delete_reminder_from_db(user_id, time, message):
    conn = sqlite3.connect("reminders.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM reminders WHERE user_id = ? AND time = ? AND message = ?", (user_id, time, message))
    conn.commit()
    conn.close()


def load_reminders_from_file():
    try:
        with open(REMINDERS_FILE, "r") as file:
            data = file.read().strip()
            if not data:  # Если файл пуст
                return {}
            return json.loads(data)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


# Helper function to check reminders asynchronously
async def check_reminders():
    while True:
        now = datetime.now()
        to_remove = []

        for user_id, user_reminders in reminders.items():
            for reminder in user_reminders:
                if reminder['time'] <= now:
                    await asyncio.sleep(0.3)
                    await bot.send_message(user_id, f"\u23f0 Напоминание: {reminder['message']}")
                    to_remove.append((user_id, reminder))

        for user_id, reminder in to_remove:
            reminders[user_id].remove(reminder)
            delete_reminder_from_db(user_id, reminder['time'].strftime('%H:%M-%d.%m.%Y'), reminder['message'])

        # save_reminders_to_file()
        await asyncio.sleep(5)  # Check every 30 seconds


@dp.message(Command(commands=['start']))
async def start_handler(message: types.Message):
    await message.answer("Привет! Я бот-напоминалка. Выберите опцию ниже:", reply_markup=main_keyboard)


@dp.message(Command(commands=['cancel']))
async def cancel_handler(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=main_keyboard)


@dp.message(lambda message: message.text == "✉ Создать напоминание")
async def create_reminder_handler(message: types.Message, state: FSMContext):
    user_message_time = message.date
    formatted_time = user_message_time.strftime('%H:%M-%d.%m.%Y')

    await message.answer(f"Пожалуйста, введите напоминание в формате:\n"
                         f"{formatted_time}|тема напоминания\n", reply_markup=types.ReplyKeyboardRemove())
    await state.set_state(ReminderStates.waiting_for_reminder_time)


@dp.message(ReminderStates.waiting_for_reminder_time)
async def set_reminder(message: types.Message, state: FSMContext):
    try:
        data = message.text.split('|', 1)
        if len(data) != 2:
            await state.clear()
            await message.answer("Неверный формат", reply_markup=main_keyboard)

        time_str, reminder_message = data
        reminder_time = datetime.strptime(time_str, "%H:%M-%d.%m.%Y")

        if reminder_time <= datetime.now():
            await state.clear()
            await message.answer("Время должно быть в будущем", reply_markup=main_keyboard)

        user_id = message.from_user.id
        if user_id not in reminders:
            reminders[user_id] = []

        reminders[user_id].append({
            'time': reminder_time,
            'message': reminder_message,
            'remaining': reminder_time - datetime.now()
        })

        save_reminder_to_db(user_id, time_str, reminder_message)

        await state.clear()
        await message.answer(f"Напоминание установлено на {time_str}: {reminder_message}", reply_markup=main_keyboard)

    except ValueError:
        await state.clear()
        await message.answer(f"Попробуйте ещё раз в правильном формате.", reply_markup=main_keyboard)


@dp.message(lambda message: message.text == "🔎 Посмотреть все напоминания")
async def view_reminders_handler(message: types.Message):
    user_id = message.from_user.id  # Получаем ID пользователя
    conn = sqlite3.connect("reminders.db")
    cursor = conn.cursor()

    # Фильтруем напоминания по user_id
    cursor.execute("SELECT user_id, time, message FROM reminders WHERE user_id = ?", (user_id,))
    reminders = cursor.fetchall()
    conn.close()

    if not reminders:
        await message.answer("Нет напоминаний.", reply_markup=main_keyboard)
        return

    response = "——Список ваших напоминаний——\n"

    # Цикл для обработки каждого напоминания
    for reminder in reminders:
        user_id, time_str, db_message = reminder  # Переименовано переменное 'message' в 'db_message'

        # Преобразуем строку времени в объект datetime
        try:
            time_obj = datetime.strptime(time_str, '%H:%M-%d.%m.%Y')  # Новый формат для времени
        except ValueError:
            await message.answer(f"Ошибка в формате времени: {time_str}", reply_markup=main_keyboard)
            return

        remaining_time = time_obj - datetime.now()
        remaining_seconds = int(remaining_time.total_seconds())

        months = remaining_seconds // (30 * 24 * 3600)  # Количество полных месяцев
        remaining_seconds %= (30 * 24 * 3600)

        days = remaining_seconds // (24 * 3600)  # Количество полных дней
        remaining_seconds %= (24 * 3600)

        hours = remaining_seconds // 3600  # Количество полных часов
        remaining_seconds %= 3600

        minutes = remaining_seconds // 60  # Количество полных минут
        seconds = remaining_seconds % 60  # Оставшиеся секунды

        # Формируем строку для текущего напоминания
        response += (f"id {user_id}\n"
                     f"🕒 Время напоминания: *{time_obj.strftime('%H:%M %d.%m.%Y')}*\n"
                     f"📜 Сообщение: *{db_message}*\n"
                     f"⏳ Осталось времени:\n"
                     f"📅 Месяцев: *{months}* | Дней: *{days}*\n"
                     f"⏰ Часов: **{hours}** | Минут: *{minutes}* | Секунд: *{seconds}*\n"
                     f"——————————————\n")

    # Отправляем все напоминания
    await message.answer(response, reply_markup=main_keyboard, parse_mode='Markdown')


@dp.startup.register
async def on_startup():
    global reminders

    init_db()

    db_reminders = load_reminders_from_db()
    for user_id, time_str, message in db_reminders:
        reminder_time = datetime.strptime(time_str, "%H:%M-%d.%m.%Y")
        if user_id not in reminders:
            reminders[user_id] = []

        reminders[user_id].append({
            'time': reminder_time,
            'message': message,
            'remaining': reminder_time - datetime.now()
        })

    file_reminders = load_reminders_from_file()
    for user_id, user_reminders in file_reminders.items():
        if int(user_id) not in reminders:
            reminders[int(user_id)] = []

        for reminder in user_reminders:
            reminders[int(user_id)].append({
                'time': datetime.fromisoformat(reminder['time']),
                'message': reminder['message'],
                'remaining': datetime.fromisoformat(reminder['time']) - datetime.now()
            })

    asyncio.create_task(check_reminders())


@dp.message()
async def handle_any_message(message: types.Message):
    await message.answer(f"Создайте напоминание или посмотрите свои напоминания", reply_markup=main_keyboard)


if __name__ == "__main__":
    dp.run_polling(bot)
