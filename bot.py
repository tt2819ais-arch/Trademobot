"""
Telegram Bot — Капча → Анкета → Реферал → Тикеты → Админ-панель
aiogram 3.x · FSM · MemoryStorage
"""

import asyncio
import random
import time
from typing import Dict, Optional

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

# ══════════════════════ НАСТРОЙКИ ══════════════════════
TOKEN = "6948724722:AAFkuxkpV7DpKooFMtrlxVLF6d9hc7wJ0ns"
ADMINS = [5426581017]
ADMIN_CHAT_ID = -1003852413098
SPECIAL_USER_ID = 6739304697

FRUITS = [
    ("🍎", "Яблоко"), ("🍌", "Банан"), ("🍒", "Вишня"), ("🍊", "Апельсин"),
    ("🍇", "Виноград"), ("🍓", "Клубника"), ("🍑", "Персик"), ("🥝", "Киви"),
]
USERS_PER_PAGE = 10
TICKETS_PER_PAGE = 5

# ══════════════════ ХРАНИЛИЩА ══════════════════
registered_users: Dict[int, dict] = {}
started_users: Dict[int, dict] = {}
user_profiles: Dict[int, dict] = {}
managers: Dict[int, dict] = {}
applications: Dict[str, dict] = {}
tickets: Dict[int, dict] = {}
ticket_counter: int = 0
user_blocks: Dict[int, float] = {}
captcha_attempts: Dict[int, int] = {}
captcha_answer: Dict[int, str] = {}
taken_apps: Dict[str, dict] = {}
# менеджер ждёт ссылку на группу: mgr_id → app_key
waiting_group_link: Dict[int, str] = {}

# ══════════════════ FSM ══════════════════
class Form(StatesGroup):
    captcha        = State()
    fill_profile   = State()
    confirm_data   = State()
    select_bank    = State()
    referral_ask   = State()
    referral_input = State()
    final_confirm  = State()

class SupportState(StatesGroup):
    writing = State()

class ManagerState(StatesGroup):
    waiting_link = State()

class AdminState(StatesGroup):
    selecting_user    = State()
    writing_to_user   = State()
    writing_broadcast = State()
    confirm_broadcast = State()
    replying_ticket   = State()
    adding_manager    = State()

# ══════════════════ INIT ══════════════════
bot = Bot(token=TOKEN)
dp  = Dispatcher(storage=MemoryStorage())
router = Router()
router.message.filter(F.chat.type == "private")

# ══════════════════ УТИЛИТЫ ══════════════════

def is_blocked(uid: int) -> bool:
    if uid in user_blocks:
        if time.time() < user_blocks[uid]:
            return True
        del user_blocks[uid]
        captcha_attempts.pop(uid, None)
    return False


def build_captcha(uid: int):
    pool = random.sample(FRUITS, 4)
    correct = random.choice(pool)
    captcha_answer[uid] = f"cap|{correct[0]}|{correct[1]}"
    rows = [[InlineKeyboardButton(text=f"{e} {n}",
             callback_data=f"cap|{e}|{n}")] for e, n in pool]
    random.shuffle(rows)
    return InlineKeyboardMarkup(inline_keyboard=rows), f"{correct[0]} {correct[1]}"


def find_user_by_username(username: str) -> Optional[int]:
    username = username.lower().lstrip("@")
    for uid, info in registered_users.items():
        if info.get("username") and info["username"].lower() == username:
            return uid
    return None


def menu_kb(uid: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="📋 Заполнить анкету", callback_data="go_profile")],
        [InlineKeyboardButton(text="🎫 Поддержка",       callback_data="go_support")],
    ]
    if uid in ADMINS:
        rows.append([InlineKeyboardButton(text="⚙️ Админ-панель", callback_data="go_admin")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Пользователи",         callback_data="adm_users:0")],
        [InlineKeyboardButton(text="📋 Кто нажал /start",     callback_data="adm_started:0")],
        [InlineKeyboardButton(text="👔 Менеджеры",            callback_data="adm_managers")],
        [InlineKeyboardButton(text="✉️ Написать пользователю", callback_data="adm_write")],
        [InlineKeyboardButton(text="📢 Рассылка",             callback_data="adm_bc")],
        [InlineKeyboardButton(text="🎫 Тикеты",              callback_data="adm_tickets:0")],
        [InlineKeyboardButton(text="🔙 Главное меню",         callback_data="adm_to_menu")],
    ])


async def safe_edit(msg: Message, text: str, kb=None):
    try:
        await msg.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        try:
            await msg.delete()
        except Exception:
            pass
        await bot.send_message(msg.chat.id, text, reply_markup=kb, parse_mode="HTML")


async def show_final_confirm(target: Message, state: FSMContext):
    data = await state.get_data()
    ref_uname = data.get("referrer_username")
    if ref_uname:
        ref_id = data.get("referrer_id")
        ref = f"@{ref_uname}" if ref_id else f"@{ref_uname} (⚠️ не зарегистрирован)"
    else:
        ref = "пришёл сам"
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Отправить заявку", callback_data="submit"),
        InlineKeyboardButton(text="🔙 Назад",           callback_data="back_ref"),
    ]])
    await target.answer(
        f"📋 <b>Итоговая анкета:</b>\n\n"
        f"👤 ФИО: {data['fio']}\n💳 Карта: <code>{data['card']}</code>\n"
        f"🏦 Счёт: <code>{data['account']}</code>\n📱 Телефон: {data['phone']}\n"
        f"🏦 Банк: {data['bank']}\n🤝 Привёл: {ref}\n\nОтправить заявку?",
        reply_markup=kb, parse_mode="HTML",
    )
    await state.set_state(Form.final_confirm)


async def show_managers_list(cb: CallbackQuery):
    lines = ["👔 <b>Менеджеры</b>\n"]
    rows = []
    if not managers:
        lines.append("Список пуст.")
    else:
        for uid, info in managers.items():
            un = f"@{info['username']}" if info.get("username") else "—"
            lines.append(f"• <code>{uid}</code> | {un} | {info.get('full_name', '—')}")
            rows.append([InlineKeyboardButton(
                text=f"❌ Удалить {un or uid}", callback_data=f"adm_rm_mgr:{uid}"
            )])
    rows.append([InlineKeyboardButton(text="➕ Добавить менеджера", callback_data="adm_add_mgr")])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="adm_back_panel")])
    await safe_edit(cb.message, "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows))


PROFILE_TEXT = (
    "📋 <b>Заполните профиль одним сообщением.</b>\n\n"
    "Отправьте <b>фото</b> (скрин трат за прошлый и текущий месяц) "
    "ФИО , Номер Карты , Номер Счета , Номер Телефона. \n\n"
    "<pre>Иванов Иван Иванович\n"
    "1234567890123456\n"
    "12345678901234567890\n"
    "+79991234567</pre>"
)


# ╔═══════════════════════════════════════════════════════╗
# ║                /start  +  КАПЧА                       ║
# ╚═══════════════════════════════════════════════════════╝

@router.message(Command("start"))
async def cmd_start(msg: Message, state: FSMContext):
    uid = msg.from_user.id
    started_users[uid] = {
        "username": msg.from_user.username,
        "full_name": msg.from_user.full_name,
    }
    if is_blocked(uid):
        left = int(user_blocks[uid] - time.time())
        await msg.answer(f"⛔ Вы заблокированы. Подождите {left} сек.")
        return
    await state.clear()
    captcha_attempts[uid] = 0
    kb, label = build_captcha(uid)
    await msg.answer(
        f"👋 Добро пожаловать!\nПройдите проверку — нажмите на <b>{label}</b>",
        reply_markup=kb, parse_mode="HTML",
    )
    await state.set_state(Form.captcha)


@router.callback_query(F.data.startswith("cap|"), Form.captcha)
async def captcha_cb(cb: CallbackQuery, state: FSMContext):
    uid = cb.from_user.id
    if is_blocked(uid):
        await cb.answer("⛔ Заблокировано.", show_alert=True)
        return
    if cb.data == captcha_answer.get(uid):
        captcha_attempts.pop(uid, None)
        captcha_answer.pop(uid, None)
        registered_users[uid] = {
            "username": cb.from_user.username,
            "full_name": cb.from_user.full_name,
            "registered_at": time.time(),
        }
        await cb.message.edit_text("✅ Капча пройдена!")
        await cb.message.answer("📌 <b>Главное меню</b>",
                                reply_markup=menu_kb(uid), parse_mode="HTML")
        await state.clear()
        await cb.answer()
    else:
        n = captcha_attempts.get(uid, 0) + 1
        captcha_attempts[uid] = n
        if n >= 3:
            user_blocks[uid] = time.time() + 120
            await cb.message.edit_text(
                "❌ Слишком много неверных попыток.\nДоступ заблокирован на 2 минуты.")
            await state.clear()
            await cb.answer()
        else:
            await cb.answer(f"❌ Неверно! Осталось попыток: {3 - n}", show_alert=True)


# ╔═══════════════════════════════════════════════════════╗
# ║                ЗАПОЛНЕНИЕ ПРОФИЛЯ                     ║
# ╚═══════════════════════════════════════════════════════╝

@router.message(Form.fill_profile, F.photo)
async def profile_photo(msg: Message, state: FSMContext):
    if is_blocked(msg.from_user.id):
        return
    caption = msg.caption or ""
    lines = [l.strip() for l in caption.strip().splitlines() if l.strip()]
    if len(lines) < 4:
        await msg.answer("❌ В подписи 4 строки: ФИО / Карта / Счёт / Телефон.")
        return
    fio = lines[0]
    card = lines[1].replace(" ", "").replace("-", "")
    account = lines[2].replace(" ", "").replace("-", "")
    phone = lines[3]
    if not card.isdigit() or len(card) != 16:
        await msg.answer("❌ Ошибка в номере карты (16 цифр).\n/start — заново")
        await state.clear(); return
    if not account.isdigit() or len(account) != 20:
        await msg.answer("❌ Ошибка в номере счёта (20 цифр).\n/start — заново")
        await state.clear(); return
    await state.update_data(fio=fio, card=card, account=account,
                            phone=phone, photo_id=msg.photo[-1].file_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Да, всё верно",    callback_data="prof_ok"),
        InlineKeyboardButton(text="❌ Заполнить заново", callback_data="prof_redo"),
    ]])
    await msg.answer(
        f"📋 <b>Проверьте данные:</b>\n\n"
        f"👤 ФИО: {fio}\n💳 Карта: <code>{card}</code>\n"
        f"🏦 Счёт: <code>{account}</code>\n📱 Телефон: {phone}\n\nВсё верно?",
        reply_markup=kb, parse_mode="HTML")
    await state.set_state(Form.confirm_data)


@router.message(Form.fill_profile)
async def profile_no_photo(msg: Message, state: FSMContext):
    await msg.answer("❌ Отправьте <b>фото</b> с подписью (ФИО, карта, счёт, телефон).",
                     parse_mode="HTML")


# ╔═══════════════════════════════════════════════════════╗
# ║            ПОДТВЕРЖДЕНИЕ → БАНК → РЕФЕРАЛ             ║
# ╚═══════════════════════════════════════════════════════╝

@router.callback_query(F.data == "prof_ok", Form.confirm_data)
async def prof_ok(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_reply_markup()
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🏦 Т-Банк",     callback_data="bank_tbank"),
        InlineKeyboardButton(text="🏦 Альфа-Банк", callback_data="bank_alfa"),
    ]])
    await cb.message.answer("🏦 Укажите ваш банк:", reply_markup=kb)
    await state.set_state(Form.select_bank)
    await cb.answer()


@router.callback_query(F.data == "prof_redo", Form.confirm_data)
async def prof_redo(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_reply_markup()
    await cb.message.answer(PROFILE_TEXT, parse_mode="HTML")
    await state.set_state(Form.fill_profile)
    await cb.answer()


@router.callback_query(F.data.startswith("bank_"), Form.select_bank)
async def bank_select(cb: CallbackQuery, state: FSMContext):
    bank = "Т-Банк" if cb.data == "bank_tbank" else "Альфа-Банк"
    await state.update_data(bank=bank)
    await cb.message.edit_reply_markup()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Да, укажу кто",    callback_data="ref_yes")],
        [InlineKeyboardButton(text="➡️ Нет, пришёл сам", callback_data="ref_no")],
    ])
    await cb.message.answer("🤝 Вас кто-то привёл?", reply_markup=kb)
    await state.set_state(Form.referral_ask)
    await cb.answer()


@router.callback_query(F.data == "ref_yes", Form.referral_ask)
async def ref_yes(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_reply_markup()
    await cb.message.answer("Введите юзернейм пригласившего (например @username):")
    await state.set_state(Form.referral_input)
    await cb.answer()


@router.callback_query(F.data == "ref_no", Form.referral_ask)
async def ref_no(cb: CallbackQuery, state: FSMContext):
    await state.update_data(referrer_username=None, referrer_id=None)
    await cb.message.edit_reply_markup()
    await show_final_confirm(cb.message, state)
    await cb.answer()


@router.message(Form.referral_input, F.text)
async def ref_input(msg: Message, state: FSMContext):
    username = msg.text.strip().lstrip("@")
    if not username:
        await msg.answer("❌ Введите юзернейм.")
        return
    referrer_id = find_user_by_username(username)
    await state.update_data(referrer_username=username, referrer_id=referrer_id)
    if not referrer_id:
        await msg.answer(
            f"⚠️ Пользователь @{username} не зарегистрирован в этом боте!\n"
            f"Ему нужно написать /start\n\n"
            f"Заявка будет отправлена без привязки к другу."
        )
    await show_final_confirm(msg, state)


@router.message(Form.referral_input)
async def ref_input_bad(msg: Message, state: FSMContext):
    await msg.answer("❌ Отправьте юзернейм текстом.")


@router.callback_query(F.data == "back_ref", Form.final_confirm)
async def back_to_ref(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_reply_markup()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Да, укажу кто",    callback_data="ref_yes")],
        [InlineKeyboardButton(text="➡️ Нет, пришёл сам", callback_data="ref_no")],
    ])
    await cb.message.answer("🤝 Вас кто-то привёл?", reply_markup=kb)
    await state.set_state(Form.referral_ask)
    await cb.answer()


# ╔═══════════════════════════════════════════════════════╗
# ║                ОТПРАВКА ЗАЯВКИ                        ║
# ╚═══════════════════════════════════════════════════════╝

@router.callback_query(F.data == "submit", Form.final_confirm)
async def submit_app(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user = cb.from_user
    uname = f"@{user.username}" if user.username else f"ID:{user.id}"
    app_key = f"{user.id}_{int(time.time())}"
    ref_uname = data.get("referrer_username")
    ref_id = data.get("referrer_id")

    if ref_uname and ref_id:
        ref = f"@{ref_uname}"
    elif ref_uname:
        ref = f"@{ref_uname} (не зарегистрирован)"
    else:
        ref = "пришёл сам"

    applications[app_key] = {
        "user_id": user.id, "username": user.username,
        "full_name": user.full_name,
        "fio": data["fio"], "card": data["card"], "account": data["account"],
        "phone": data["phone"], "bank": data["bank"], "photo_id": data["photo_id"],
        "referrer_username": ref_uname, "referrer_id": ref_id,
        "created_at": time.time(),
    }
    user_profiles[user.id] = applications[app_key]

    caption = (
        f"📋 <b>Новая заявка</b>\n\n"
        f"👤 ФИО: {data['fio']}\n💳 Карта: <code>{data['card']}</code>\n"
        f"🏦 Счёт: <code>{data['account']}</code>\n📱 Телефон: {data['phone']}\n"
        f"🏦 Банк: {data['bank']}\n🤝 Привёл: {ref}\n\n"
        f"📩 От: {uname} (ID: <code>{user.id}</code>)"
    )
    app_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="👤 Взять в работу", callback_data=f"took:{app_key}"),
    ]])

    sent = False
    try:
        await bot.send_photo(ADMIN_CHAT_ID, photo=data["photo_id"],
                             caption=caption, reply_markup=app_kb, parse_mode="HTML")
        sent = True
    except Exception as e:
        print(f"[!] Группа: {e}")
    for aid in ADMINS:
        try:
            await bot.send_photo(aid, photo=data["photo_id"],
                                 caption=caption, reply_markup=app_kb, parse_mode="HTML")
            sent = True
        except Exception:
            pass

    await cb.message.edit_reply_markup()
    if sent:
        await cb.message.answer("✅ Заявка отправлена! Ожидайте.\n/menu — меню")
    else:
        await cb.message.answer("⚠️ Не удалось отправить заявку.")
    await state.clear()
    await cb.answer()


# ╔═══════════════════════════════════════════════════════╗
# ║     ВЗЯТЬ В РАБОТУ → МЕНЕДЖЕР СОЗДАЁТ ГРУППУ          ║
# ╚═══════════════════════════════════════════════════════╝

@router.callback_query(F.data.startswith("took:"))
async def took_user(cb: CallbackQuery, state: FSMContext):
    app_key = cb.data.split(":", 1)[1]
    mgr = cb.from_user
    mgr_name = f"@{mgr.username}" if mgr.username else mgr.full_name

    if app_key in taken_apps:
        await cb.answer("❌ Уже в работе у другого менеджера.", show_alert=True)
        return

    if mgr.id not in ADMINS and mgr.id not in managers:
        await cb.answer("⛔ Только менеджеры/админы.", show_alert=True)
        return

    app = applications.get(app_key)
    if not app:
        await cb.answer("❌ Заявка не найдена.", show_alert=True)
        return

    taken_apps[app_key] = {"id": mgr.id, "name": mgr_name}

    # обновляем кнопку в чате
    try:
        await cb.message.edit_reply_markup(
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=f"✅ В работе у {mgr_name}", callback_data="noop"),
            ]]))
    except Exception:
        pass

    # уведомляем пользователя
    app_uname = f"@{app['username']}" if app.get("username") else app.get("full_name", "Клиент")
    try:
        await bot.send_message(
            app["user_id"],
            f"🎉 <b>Ваша заявка взята в работу!</b>\n\n"
            f"Менеджер: {mgr_name}\n"
            f"Ожидайте — менеджер создаст рабочую группу и пришлёт вам приглашение.",
            parse_mode="HTML")
    except Exception:
        pass

    # запоминаем что менеджер должен прислать ссылку
    waiting_group_link[mgr.id] = app_key

    # просим менеджера создать группу
    ref_uname = app.get("referrer_username")
    ref_id = app.get("referrer_id")
    if ref_uname and ref_id:
        ref_info = f"🤝 Друг: @{ref_uname} — тоже получит приглашение"
    elif ref_uname and not ref_id:
        ref_info = f"🤝 Друг: @{ref_uname} — ⚠️ не зарегистрирован в боте (не получит приглашение)"
    else:
        ref_info = "🤝 Пришёл сам (без реферера)"

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="❌ Отмена", callback_data=f"cancel_link:{app_key}"),
    ]])

    try:
        await bot.send_message(
            mgr.id,
            f"📋 <b>Вы взяли заявку в работу</b>\n\n"
            f"👤 Клиент: {app_uname} (ID: <code>{app['user_id']}</code>)\n"
            f"👤 ФИО: {app['fio']}\n"
            f"🏦 Банк: {app['bank']}\n"
            f"{ref_info}\n\n"
            f"📌 <b>Создайте группу и отправьте сюда ссылку-приглашение.</b>\n"
            f"Пользователю придёт уведомление с приглашением в группу.",
            reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        print(f"[!] Не удалось написать менеджеру {mgr.id}: {e}")

    await cb.answer("✅ Вы взяли в работу. Создайте группу и отправьте ссылку боту.", show_alert=True)


@router.callback_query(F.data.startswith("cancel_link:"))
async def cancel_link(cb: CallbackQuery, state: FSMContext):
    app_key = cb.data.split(":", 1)[1]
    if waiting_group_link.get(cb.from_user.id) == app_key:
        del waiting_group_link[cb.from_user.id]
    await cb.message.edit_text("❌ Отменено. Вы можете отправить ссылку позже через ЛС пользователю.")
    await cb.answer()


@router.callback_query(F.data == "noop")
async def noop(cb: CallbackQuery):
    await cb.answer("Заявка уже в работе.", show_alert=True)


# ╔═══════════════════════════════════════════════════════╗
# ║    МЕНЕДЖЕР ПРИСЫЛАЕТ ССЫЛКУ НА ГРУППУ                ║
# ╚═══════════════════════════════════════════════════════╝

async def try_handle_group_link(msg: Message, state: FSMContext) -> bool:
    """Если менеджер ожидает отправки ссылки — обрабатываем. Возвращаем True если обработали."""
    uid = msg.from_user.id
    if uid not in waiting_group_link:
        return False

    text = (msg.text or "").strip()
    if not text:
        return False

    # проверяем что это похоже на ссылку
    if not ("t.me/" in text or "telegram." in text.lower()):
        await msg.answer("❌ Это не похоже на ссылку-приглашение Telegram.\n"
                         "Отправьте ссылку вида https://t.me/+... или https://t.me/joinchat/...")
        return True

    app_key = waiting_group_link.pop(uid)
    app = applications.get(app_key)
    if not app:
        await msg.answer("❌ Заявка не найдена.")
        return True

    link = text
    mgr_name = f"@{msg.from_user.username}" if msg.from_user.username else msg.from_user.full_name
    app_uname = f"@{app['username']}" if app.get("username") else app.get("full_name", "Клиент")
    sent_to = []

    # 1. клиенту
    try:
        await bot.send_message(
            app["user_id"],
            f"🔗 <b>Менеджер {mgr_name} создал рабочую группу!</b>\n\n"
            f"Присоединяйтесь: {link}",
            parse_mode="HTML")
        sent_to.append(f"клиент ({app_uname})")
    except Exception:
        pass

    # 2. спец-пользователю
    try:
        await bot.send_message(
            SPECIAL_USER_ID,
            f"🔗 <b>Новая рабочая группа</b>\n\n"
            f"Клиент: {app_uname}\nМенеджер: {mgr_name}\n\n"
            f"Ссылка: {link}",
            parse_mode="HTML")
        sent_to.append("спец-пользователь")
    except Exception:
        pass

    # 3. рефереру (если зарегистрирован)
    ref_uname = app.get("referrer_username")
    ref_id = app.get("referrer_id")
    if ref_uname:
        if ref_id:
            try:
                await bot.send_message(
                    ref_id,
                    f"🔗 <b>Ваш приглашённый ({app_uname}) одобрен!</b>\n\n"
                    f"Присоединяйтесь в рабочую группу: {link}",
                    parse_mode="HTML")
                sent_to.append(f"реферер (@{ref_uname})")
            except Exception:
                pass
        else:
            await msg.answer(
                f"⚠️ Пользователь @{ref_uname} не зарегистрирован в этом боте!\n"
                f"Ему нужно написать /start — приглашение не отправлено.")

    report = ", ".join(sent_to) if sent_to else "никому"
    await msg.answer(f"✅ Ссылка отправлена: {report}")
    return True


# ╔═══════════════════════════════════════════════════════╗
# ║              НАВИГАЦИЯ                                ║
# ╚═══════════════════════════════════════════════════════╝

@router.message(Command("menu"))
async def cmd_menu(msg: Message, state: FSMContext):
    uid = msg.from_user.id
    if uid not in registered_users and uid not in ADMINS:
        await msg.answer("Сначала: /start"); return
    await state.clear()
    waiting_group_link.pop(uid, None)
    await msg.answer("📌 <b>Главное меню</b>", reply_markup=menu_kb(uid), parse_mode="HTML")


@router.message(Command("support"))
async def cmd_support(msg: Message, state: FSMContext):
    uid = msg.from_user.id
    if uid not in registered_users and uid not in ADMINS:
        await msg.answer("Сначала: /start"); return
    await state.clear()
    await msg.answer("✏️ Опишите проблему (текст или фото).\nОтмена: /menu")
    await state.set_state(SupportState.writing)


@router.message(Command("admin"))
async def cmd_admin(msg: Message, state: FSMContext):
    if msg.from_user.id not in ADMINS:
        await msg.answer("⛔ Нет доступа."); return
    await state.clear()
    await msg.answer("⚙️ <b>Админ-панель</b>", reply_markup=admin_kb(), parse_mode="HTML")


@router.callback_query(F.data == "go_profile")
async def go_profile(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_reply_markup()
    await cb.message.answer(PROFILE_TEXT, parse_mode="HTML")
    await state.set_state(Form.fill_profile)
    await cb.answer()


@router.callback_query(F.data == "go_support")
async def go_support(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_reply_markup()
    await cb.message.answer("✏️ Опишите проблему (текст или фото).\nОтмена: /menu")
    await state.set_state(SupportState.writing)
    await cb.answer()


@router.callback_query(F.data == "go_admin")
async def go_admin(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in ADMINS:
        await cb.answer("Нет доступа.", show_alert=True); return
    await safe_edit(cb.message, "⚙️ <b>Админ-панель</b>", admin_kb())
    await state.clear(); await cb.answer()


@router.callback_query(F.data == "adm_to_menu")
async def adm_to_menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_edit(cb.message, "📌 <b>Главное меню</b>", menu_kb(cb.from_user.id))
    await cb.answer()


@router.callback_query(F.data == "adm_back_panel")
async def adm_back(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in ADMINS:
        await cb.answer("Нет доступа.", show_alert=True); return
    await state.clear()
    await safe_edit(cb.message, "⚙️ <b>Админ-панель</b>", admin_kb())
    await cb.answer()


# ╔═══════════════════════════════════════════════════════╗
# ║                ТИКЕТЫ (пользователь)                  ║
# ╚═══════════════════════════════════════════════════════╝

@router.message(SupportState.writing, F.text)
async def ticket_text(msg: Message, state: FSMContext):
    global ticket_counter
    ticket_counter += 1
    tid = ticket_counter
    user = msg.from_user
    tickets[tid] = {
        "user_id": user.id, "username": user.username,
        "full_name": user.full_name, "message": msg.text,
        "photo_id": None, "status": "open",
        "created_at": time.time(), "answer": None, "answered_by": None,
    }
    await msg.answer(f"✅ Тикет #{tid} создан.\n/menu — меню")
    await state.clear()
    uname = f"@{user.username}" if user.username else user.full_name
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="💬 Ответить", callback_data=f"treply:{tid}"),
    ]])
    for aid in ADMINS:
        try:
            await bot.send_message(aid,
                f"🎫 <b>Тикет #{tid}</b>\n\n👤 {uname} "
                f"(ID: <code>{user.id}</code>)\n💬 {msg.text}",
                reply_markup=kb, parse_mode="HTML")
        except Exception:
            pass


@router.message(SupportState.writing, F.photo)
async def ticket_photo(msg: Message, state: FSMContext):
    global ticket_counter
    ticket_counter += 1
    tid = ticket_counter
    user = msg.from_user
    body = msg.caption or "(фото)"
    tickets[tid] = {
        "user_id": user.id, "username": user.username,
        "full_name": user.full_name, "message": body,
        "photo_id": msg.photo[-1].file_id, "status": "open",
        "created_at": time.time(), "answer": None, "answered_by": None,
    }
    await msg.answer(f"✅ Тикет #{tid} создан.\n/menu — меню")
    await state.clear()
    uname = f"@{user.username}" if user.username else user.full_name
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="💬 Ответить", callback_data=f"treply:{tid}"),
    ]])
    for aid in ADMINS:
        try:
            await bot.send_photo(aid, photo=msg.photo[-1].file_id,
                caption=f"🎫 <b>Тикет #{tid}</b>\n\n👤 {uname} "
                f"(ID: <code>{user.id}</code>)\n💬 {body}",
                reply_markup=kb, parse_mode="HTML")
        except Exception:
            pass


@router.message(SupportState.writing)
async def ticket_bad(msg: Message):
    await msg.answer("❌ Текст или фото с подписью.")


# ╔═══════════════════════════════════════════════════════╗
# ║          АДМИН — КТО НАЖАЛ /start                     ║
# ╚═══════════════════════════════════════════════════════╝

@router.callback_query(F.data.startswith("adm_started:"))
async def adm_started(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in ADMINS:
        await cb.answer("Нет доступа.", show_alert=True); return
    page = int(cb.data.split(":")[1])
    items = list(started_users.items())
    total = len(items)
    if not total:
        await safe_edit(cb.message, "📋 <b>Кто нажал /start</b>\n\nНикто.",
                        InlineKeyboardMarkup(inline_keyboard=[[
                            InlineKeyboardButton(text="🔙", callback_data="adm_back_panel")]]))
        await cb.answer(); return
    pages = (total + USERS_PER_PAGE - 1) // USERS_PER_PAGE
    page = max(0, min(page, pages - 1))
    chunk = items[page * USERS_PER_PAGE:(page + 1) * USERS_PER_PAGE]
    lines = [f"📋 <b>Кто нажал /start ({total})</b> стр. {page + 1}/{pages}\n"]
    for i, (uid, info) in enumerate(chunk, start=page * USERS_PER_PAGE + 1):
        un = f"@{info['username']}" if info.get("username") else "—"
        name = info.get("full_name", "—")
        lines.append(f"{i}. {un} | {name}")
    nav = []
    if page > 0: nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"adm_started:{page-1}"))
    if page < pages - 1: nav.append(InlineKeyboardButton(text="➡️", callback_data=f"adm_started:{page+1}"))
    rows = []
    if nav: rows.append(nav)
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="adm_back_panel")])
    await safe_edit(cb.message, "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows))
    await cb.answer()


# ╔═══════════════════════════════════════════════════════╗
# ║          АДМИН — ПОЛЬЗОВАТЕЛИ (зарег.)                ║
# ╚═══════════════════════════════════════════════════════╝

@router.callback_query(F.data.startswith("adm_users:"))
async def adm_users(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in ADMINS:
        await cb.answer("Нет доступа.", show_alert=True); return
    page = int(cb.data.split(":")[1])
    items = list(registered_users.items())
    total = len(items)
    if not total:
        await safe_edit(cb.message, "👥 <b>Пользователи</b>\n\nПусто.",
                        InlineKeyboardMarkup(inline_keyboard=[[
                            InlineKeyboardButton(text="🔙", callback_data="adm_back_panel")]]))
        await cb.answer(); return
    pages = (total + USERS_PER_PAGE - 1) // USERS_PER_PAGE
    page = max(0, min(page, pages - 1))
    chunk = items[page * USERS_PER_PAGE:(page + 1) * USERS_PER_PAGE]
    lines = [f"👥 <b>Пользователи ({total})</b> стр. {page + 1}/{pages}\n"]
    for uid, info in chunk:
        un = f"@{info['username']}" if info.get("username") else "—"
        lines.append(f"• <code>{uid}</code> | {un} | {info['full_name']}")
    nav = []
    if page > 0: nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"adm_users:{page-1}"))
    if page < pages - 1: nav.append(InlineKeyboardButton(text="➡️", callback_data=f"adm_users:{page+1}"))
    rows = []
    if nav: rows.append(nav)
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="adm_back_panel")])
    await safe_edit(cb.message, "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows))
    await cb.answer()


# ╔═══════════════════════════════════════════════════════╗
# ║                АДМИН — МЕНЕДЖЕРЫ                      ║
# ╚═══════════════════════════════════════════════════════╝

@router.callback_query(F.data == "adm_managers")
async def adm_managers_cb(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in ADMINS:
        await cb.answer("Нет доступа.", show_alert=True); return
    await show_managers_list(cb)
    await cb.answer()


@router.callback_query(F.data == "adm_add_mgr")
async def adm_add_mgr(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in ADMINS:
        await cb.answer("Нет доступа.", show_alert=True); return
    await safe_edit(cb.message,
                    "Введите <b>ID</b> или <b>@username</b> нового менеджера:\n\nОтмена: /admin")
    await state.set_state(AdminState.adding_manager)
    await cb.answer()


@router.message(AdminState.adding_manager, F.text)
async def adm_add_mgr_input(msg: Message, state: FSMContext):
    if msg.from_user.id not in ADMINS:
        return
    text = msg.text.strip()
    uid = None
    if text.startswith("@"):
        uid = find_user_by_username(text.lstrip("@"))
        if uid is None:
            await msg.answer("❌ Пользователь не найден среди зарегистрированных.\n"
                             "Введите числовой ID или /admin.")
            return
    elif text.isdigit():
        uid = int(text)
    else:
        await msg.answer("❌ Введите ID или @username.\nОтмена: /admin")
        return
    info = registered_users.get(uid, {})
    managers[uid] = {
        "username": info.get("username"),
        "full_name": info.get("full_name", "Неизвестен"),
        "added_by": msg.from_user.id,
    }
    name = info.get("full_name", str(uid))
    await msg.answer(f"✅ Менеджер <code>{uid}</code> ({name}) добавлен.", parse_mode="HTML")
    try:
        await bot.send_message(uid,
            "🎉 <b>Вам назначена роль: Менеджер ПГ</b>\n\n"
            "Теперь вы можете принимать заявки пользователей, "
            "нажимая кнопку «Взять в работу» в рабочем чате.\n\n"
            "После принятия заявки — создайте группу и отправьте ссылку боту.",
            parse_mode="HTML")
    except Exception as e:
        await msg.answer(f"⚠️ Не удалось уведомить: {e}")
    await state.clear()
    await msg.answer("⚙️ <b>Админ-панель</b>", reply_markup=admin_kb(), parse_mode="HTML")


@router.callback_query(F.data.startswith("adm_rm_mgr:"))
async def adm_rm_mgr(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in ADMINS:
        await cb.answer("Нет доступа.", show_alert=True); return
    uid = int(cb.data.split(":")[1])
    name = managers.get(uid, {}).get("full_name", str(uid))
    managers.pop(uid, None)
    try:
        await bot.send_message(uid,
            "⚠️ Ваша роль <b>Менеджер ПГ</b> была снята администратором.",
            parse_mode="HTML")
    except Exception:
        pass
    await cb.answer(f"Менеджер {name} удалён.", show_alert=True)
    await show_managers_list(cb)


# ╔═══════════════════════════════════════════════════════╗
# ║           АДМИН — НАПИСАТЬ ПОЛЬЗОВАТЕЛЮ               ║
# ╚═══════════════════════════════════════════════════════╝

@router.callback_query(F.data == "adm_write")
async def adm_write(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in ADMINS:
        await cb.answer("Нет доступа.", show_alert=True); return
    await safe_edit(cb.message, "✉️ Введите <b>ID</b> пользователя:\n\nОтмена: /admin")
    await state.set_state(AdminState.selecting_user)
    await cb.answer()


@router.message(AdminState.selecting_user, F.text)
async def adm_uid_input(msg: Message, state: FSMContext):
    if msg.from_user.id not in ADMINS: return
    if not (msg.text or "").strip().isdigit():
        await msg.answer("❌ Числовой ID.\nОтмена: /admin"); return
    target = int(msg.text.strip())
    await state.update_data(target_uid=target)
    name = registered_users.get(target, {}).get("full_name", "неизвестен")
    await msg.answer(f"📝 Сообщение для <code>{target}</code> ({name}).\n"
                     f"Текст или фото.\nОтмена: /admin", parse_mode="HTML")
    await state.set_state(AdminState.writing_to_user)


@router.message(AdminState.writing_to_user, F.text)
async def adm_send_txt(msg: Message, state: FSMContext):
    data = await state.get_data()
    try:
        await bot.send_message(data["target_uid"],
            f"📩 <b>Сообщение от администрации:</b>\n\n{msg.text}", parse_mode="HTML")
        await msg.answer("✅ Отправлено.")
    except Exception as e:
        await msg.answer(f"❌ {e}")
    await state.clear()
    await msg.answer("⚙️ <b>Админ-панель</b>", reply_markup=admin_kb(), parse_mode="HTML")


@router.message(AdminState.writing_to_user, F.photo)
async def adm_send_ph(msg: Message, state: FSMContext):
    data = await state.get_data()
    try:
        await bot.send_photo(data["target_uid"], photo=msg.photo[-1].file_id,
            caption=f"📩 <b>От администрации:</b>\n\n{msg.caption or ''}", parse_mode="HTML")
        await msg.answer("✅ Отправлено.")
    except Exception as e:
        await msg.answer(f"❌ {e}")
    await state.clear()
    await msg.answer("⚙️ <b>Админ-панель</b>", reply_markup=admin_kb(), parse_mode="HTML")


@router.message(AdminState.writing_to_user)
async def adm_send_bad(msg: Message):
    await msg.answer("❌ Текст или фото.")


# ╔═══════════════════════════════════════════════════════╗
# ║                АДМИН — РАССЫЛКА                       ║
# ╚═══════════════════════════════════════════════════════╝

@router.callback_query(F.data == "adm_bc")
async def adm_bc_start(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in ADMINS:
        await cb.answer("Нет доступа.", show_alert=True); return
    total = len(registered_users)
    await safe_edit(cb.message,
        f"📢 Сообщение для рассылки ({total} чел.).\nТекст или фото.\nОтмена: /admin")
    await state.set_state(AdminState.writing_broadcast)
    await cb.answer()


@router.message(AdminState.writing_broadcast, F.text)
async def adm_bc_txt(msg: Message, state: FSMContext):
    await state.update_data(bc_text=msg.text, bc_photo=None)
    total = len(registered_users)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"✅ Отправить ({total})", callback_data="bc_yes"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="adm_back_panel"),
    ]])
    await msg.answer(f"📢 <b>Предпросмотр:</b>\n\n{msg.text}\n\nОтправить?",
                     reply_markup=kb, parse_mode="HTML")
    await state.set_state(AdminState.confirm_broadcast)


@router.message(AdminState.writing_broadcast, F.photo)
async def adm_bc_ph(msg: Message, state: FSMContext):
    await state.update_data(bc_text=msg.caption or "", bc_photo=msg.photo[-1].file_id)
    total = len(registered_users)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"✅ Отправить ({total})", callback_data="bc_yes"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="adm_back_panel"),
    ]])
    await msg.answer(f"📢 Фото + подпись:\n{msg.caption or '—'}\n\nОтправить?", reply_markup=kb)
    await state.set_state(AdminState.confirm_broadcast)


@router.message(AdminState.writing_broadcast)
async def adm_bc_bad(msg: Message):
    await msg.answer("❌ Текст или фото.")


@router.callback_query(F.data == "bc_yes", AdminState.confirm_broadcast)
async def bc_confirm(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await cb.message.edit_reply_markup()
    ok = fail = 0
    for uid in registered_users:
        try:
            if data.get("bc_photo"):
                await bot.send_photo(uid, photo=data["bc_photo"],
                    caption=f"📢 {data['bc_text']}", parse_mode="HTML")
            else:
                await bot.send_message(uid,
                    f"📢 <b>Объявление:</b>\n\n{data['bc_text']}", parse_mode="HTML")
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)
    await cb.message.answer(f"✅ Рассылка: {ok} ок / {fail} ошибок.")
    await state.clear()
    await cb.message.answer("⚙️ <b>Админ-панель</b>", reply_markup=admin_kb(), parse_mode="HTML")
    await cb.answer()


# ╔═══════════════════════════════════════════════════════╗
# ║                АДМИН — ТИКЕТЫ                         ║
# ╚═══════════════════════════════════════════════════════╝

@router.callback_query(F.data.startswith("adm_tickets:"))
async def adm_tickets(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in ADMINS:
        await cb.answer("Нет доступа.", show_alert=True); return
    page = int(cb.data.split(":")[1])
    open_t = sorted([(t, d) for t, d in tickets.items() if d["status"] == "open"],
                    key=lambda x: x[0], reverse=True)
    total = len(open_t)
    if not total:
        await safe_edit(cb.message, "🎫 <b>Тикеты</b>\n\nНет открытых.",
            InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🔙", callback_data="adm_back_panel")]]))
        await cb.answer(); return
    pages = (total + TICKETS_PER_PAGE - 1) // TICKETS_PER_PAGE
    page = max(0, min(page, pages - 1))
    chunk = open_t[page * TICKETS_PER_PAGE:(page + 1) * TICKETS_PER_PAGE]
    lines = [f"🎫 <b>Тикеты ({total})</b> стр. {page + 1}/{pages}\n"]
    rows = []
    for tid, t in chunk:
        un = f"@{t['username']}" if t.get("username") else t["full_name"]
        prev = t["message"][:30] + ("…" if len(t["message"]) > 30 else "")
        lines.append(f"#{tid} | {un}: {prev}")
        rows.append([InlineKeyboardButton(text=f"#{tid} — {un}", callback_data=f"tview:{tid}")])
    nav = []
    if page > 0: nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"adm_tickets:{page-1}"))
    if page < pages - 1: nav.append(InlineKeyboardButton(text="➡️", callback_data=f"adm_tickets:{page+1}"))
    if nav: rows.append(nav)
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="adm_back_panel")])
    await safe_edit(cb.message, "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows))
    await cb.answer()


@router.callback_query(F.data.startswith("tview:"))
async def ticket_view(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in ADMINS:
        await cb.answer("Нет доступа.", show_alert=True); return
    tid = int(cb.data.split(":")[1])
    t = tickets.get(tid)
    if not t: await cb.answer("Не найден.", show_alert=True); return
    un = f"@{t['username']}" if t.get("username") else t["full_name"]
    dt = time.strftime("%d.%m.%Y %H:%M", time.localtime(t["created_at"]))
    text = (f"🎫 <b>Тикет #{tid}</b>\n\n👤 {un} (ID: <code>{t['user_id']}</code>)\n"
            f"📅 {dt}\n📊 {t['status']}\n\n💬 {t['message']}")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Ответить", callback_data=f"treply:{tid}")],
        [InlineKeyboardButton(text="🔙 К тикетам", callback_data="adm_tickets:0")],
    ])
    try: await cb.message.delete()
    except Exception: pass
    if t.get("photo_id"):
        await bot.send_photo(cb.from_user.id, photo=t["photo_id"],
            caption=text, reply_markup=kb, parse_mode="HTML")
    else:
        await bot.send_message(cb.from_user.id, text, reply_markup=kb, parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data.startswith("treply:"))
async def ticket_reply_start(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in ADMINS:
        await cb.answer("Нет доступа.", show_alert=True); return
    tid = int(cb.data.split(":")[1])
    if tid not in tickets: await cb.answer("Не найден.", show_alert=True); return
    await state.update_data(reply_ticket_id=tid)
    await state.set_state(AdminState.replying_ticket)
    try: await cb.message.edit_reply_markup()
    except Exception: pass
    await cb.message.answer(f"✏️ Ответ на тикет #{tid}.\nОтмена: /admin")
    await cb.answer()


@router.message(AdminState.replying_ticket, F.text)
async def ticket_reply_txt(msg: Message, state: FSMContext):
    data = await state.get_data()
    tid = data["reply_ticket_id"]
    t = tickets.get(tid)
    if not t: await msg.answer("❌ Не найден."); await state.clear(); return
    try:
        await bot.send_message(t["user_id"],
            f"📩 <b>Ответ поддержки (#{tid}):</b>\n\n{msg.text}", parse_mode="HTML")
        t["status"] = "answered"; t["answer"] = msg.text
        t["answered_by"] = msg.from_user.username or str(msg.from_user.id)
        await msg.answer(f"✅ Ответ #{tid} отправлен.")
    except Exception as e:
        await msg.answer(f"❌ {e}")
    await state.clear()
    await msg.answer("⚙️ <b>Админ-панель</b>", reply_markup=admin_kb(), parse_mode="HTML")


@router.message(AdminState.replying_ticket, F.photo)
async def ticket_reply_ph(msg: Message, state: FSMContext):
    data = await state.get_data()
    tid = data["reply_ticket_id"]
    t = tickets.get(tid)
    if not t: await msg.answer("❌ Не найден."); await state.clear(); return
    try:
        await bot.send_photo(t["user_id"], photo=msg.photo[-1].file_id,
            caption=f"📩 <b>Ответ поддержки (#{tid}):</b>\n\n{msg.caption or ''}",
            parse_mode="HTML")
        t["status"] = "answered"; t["answer"] = msg.caption or "(фото)"
        t["answered_by"] = msg.from_user.username or str(msg.from_user.id)
        await msg.answer(f"✅ Ответ #{tid} отправлен.")
    except Exception as e:
        await msg.answer(f"❌ {e}")
    await state.clear()
    await msg.answer("⚙️ <b>Админ-панель</b>", reply_markup=admin_kb(), parse_mode="HTML")


@router.message(AdminState.replying_ticket)
async def ticket_reply_bad(msg: Message):
    await msg.answer("❌ Текст или фото.")


# ╔═══════════════════════════════════════════════════════╗
# ║                    FALLBACK                           ║
# ╚═══════════════════════════════════════════════════════╝

@router.message(F.text)
async def fallback_text(msg: Message, state: FSMContext):
    if is_blocked(msg.from_user.id):
        return

    # сначала проверяем: менеджер ждёт ссылку?
    handled = await try_handle_group_link(msg, state)
    if handled:
        return

    cur = await state.get_state()
    if cur is None:
        if msg.from_user.id in registered_users or msg.from_user.id in ADMINS:
            await msg.answer("📌 /menu — меню · /support — поддержка")
        else:
            await msg.answer("Нажмите /start для начала.")


@router.message()
async def fallback_other(msg: Message, state: FSMContext):
    if is_blocked(msg.from_user.id):
        return
    cur = await state.get_state()
    if cur is None:
        if msg.from_user.id in registered_users or msg.from_user.id in ADMINS:
            await msg.answer("📌 /menu — меню · /support — поддержка")
        else:
            await msg.answer("Нажмите /start для начала.")


# ╔═══════════════════════════════════════════════════════╗
# ║                     ЗАПУСК                            ║
# ╚═══════════════════════════════════════════════════════╝

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    dp.include_router(router)
    print("[✓] Бот запущен")
    print(f"    ADMIN_CHAT_ID  = {ADMIN_CHAT_ID}")
    print(f"    ADMINS         = {ADMINS}")
    print(f"    SPECIAL_USER   = {SPECIAL_USER_ID}")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
