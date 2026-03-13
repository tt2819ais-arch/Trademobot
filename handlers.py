"""
Все обработчики бота:
 - общие команды (/start, /help)
 - команды смены (/allstart, /allstop)
 - админ-команды (/add_manager, /remove_manager, /users, /stats, …)
 - ConversationHandler для создания заявки (/new)
 - callback «Принимаю»
 - Job-функция периодического тегирования
 - post_init для восстановления активных дропов после рестарта
"""

import logging
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
)
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from config import ADMIN_IDS, CREATOR_IDS, SUPERGROUP_ID, TAG_INTERVAL_SECONDS
from database import Database

logger = logging.getLogger(__name__)

# ─── Глобальный экземпляр БД ────────────────────────────────
db = Database()

# ─── Состояния ConversationHandler ──────────────────────────
(
    ASK_FIO,
    ASK_CARD,
    ASK_ACCOUNT,
    ASK_PHONE,
    ASK_DROP_USERNAME,
    ASK_BANK,
    ASK_SCREENSHOTS,
    ASK_CHAT_LINK,
    ASK_VERIFIED,
) = range(9)


# ═══════════════════════════════════════════════════════════
#  Вспомогательные функции
# ═══════════════════════════════════════════════════════════

def _register(user):
    """Зарегистрировать / обновить пользователя в БД."""
    db.upsert_user(user.id, user.username, user.first_name, user.last_name)


def _is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS


def _is_creator(uid: int) -> bool:
    """Проверяет по конфигу и по БД (для динамически добавленных)."""
    return uid in CREATOR_IDS or db.is_creator_in_db(uid)


def _mention(uid: int, username: str | None, first_name: str = "Пользователь") -> str:
    """HTML-упомин��ние: @username или ссылка tg://user."""
    if username:
        return f"@{username}"
    return f'<a href="tg://user?id={uid}">{first_name}</a>'


def _ensure_https(url: str) -> str:
    """Если ссылка без схемы — добавить https://."""
    if url and not url.startswith(("http://", "https://", "tg://")):
        return "https://" + url
    return url


# ═══════════════════════════════════════════════════════════
#  /start, /help
# ═══════════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _register(update.effective_user)
    await update.message.reply_text(
        "👋 <b>Привет!</b> Я бот для управления дропами.\n\n"
        "🔹 Менеджер → /allstart в рабочей группе\n"
        "🔹 Дроповод → /new в ЛС со мной\n"
        "🔹 Справка  → /help",
        parse_mode=ParseMode.HTML,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _register(update.effective_user)
    await update.message.reply_text(
        "📋 <b>Команды бота</b>\n\n"
        "<b>Общие:</b>\n"
        "/start — приветствие\n"
        "/help  — эта справка\n\n"
        "<b>Менеджерам (супергруппа):</b>\n"
        "/allstart — выйти на смену\n"
        "/allstop  — уйти со смены\n\n"
        "<b>Дроповодам (ЛС):</b>\n"
        "/new    — создать заявку\n"
        "/cancel — отменить заявку\n\n"
        "<b>Админам:</b>\n"
        "/add_manager &lt;ID&gt;\n"
        "/remove_manager &lt;ID&gt;\n"
        "/add_creator &lt;ID&gt;\n"
        "/remove_creator &lt;ID&gt;\n"
        "/users — все пользователи\n"
        "/stats — статистика\n"
        "/taken — взятые заявки\n"
        "/active — активные заявки",
        parse_mode=ParseMode.HTML,
    )


# ═══════════════════════════════════════════════════════════
#  /allstart, /allstop  (только в супергруппе)
# ═══════════════════════════════════════════════════════════

async def cmd_allstart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != SUPERGROUP_ID:
        await update.message.reply_text(
            "⚠️ Команда работает только в рабочей группе.")
        return

    user = update.effective_user
    _register(user)
    db.set_on_shift(user.id, True)

    await update.message.reply_text(
        f"✅ {_mention(user.id, user.username, user.first_name)}, "
        f"ты вышел на смену! Теперь ты получаешь уведомления о новых дропах.",
        parse_mode=ParseMode.HTML,
    )


async def cmd_allstop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != SUPERGROUP_ID:
        await update.message.reply_text(
            "⚠️ Команда работает только в рабочей группе.")
        return

    user = update.effective_user
    _register(user)
    db.set_on_shift(user.id, False)

    await update.message.reply_text(
        f"🔴 {_mention(user.id, user.username, user.first_name)}, "
        f"ты ушёл со смены. Уведомления отключены.",
        parse_mode=ParseMode.HTML,
    )


# ═══════════════════════════════════════════════════════════
#  Админ-команды
# ═══════════════════════════════════════════════════════════

async def cmd_add_manager(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Формат: /add_manager <user_id>")
        return
    try:
        tid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("⚠️ ID должен быть числом.")
        return
    if not db.user_exists(tid):
        db.upsert_user(tid)
    db.set_manager(tid, True)
    await update.message.reply_text(f"✅ {tid} назначен менеджером.")


async def cmd_remove_manager(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Формат: /remove_manager <user_id>")
        return
    try:
        tid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("⚠️ ID должен быть числом.")
        return
    db.set_manager(tid, False)
    db.set_on_shift(tid, False)
    await update.message.reply_text(f"✅ {tid} снят с роли менеджера.")


async def cmd_add_creator(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Формат: /add_creator <user_id>")
        return
    try:
        tid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("⚠️ ID должен быть числом.")
        return
    if not db.user_exists(tid):
        db.upsert_user(tid)
    if tid not in CREATOR_IDS:
        CREATOR_IDS.append(tid)
    db.set_creator(tid, True)
    await update.message.reply_text(f"✅ {tid} назначен дроповодом.")


async def cmd_remove_creator(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Формат: /remove_creator <user_id>")
        return
    try:
        tid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("⚠️ ID должен быть числом.")
        return
    if tid in CREATOR_IDS:
        CREATOR_IDS.remove(tid)
    db.set_creator(tid, False)
    await update.message.reply_text(f"✅ {tid} снят с роли дроповода.")


async def cmd_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    users = db.get_all_users()
    if not users:
        await update.message.reply_text("Нет зарегистрированных пользователей.")
        return

    lines = ["📋 <b>Пользователи:</b>\n"]
    for u in users:
        flags = []
        if u["on_shift"]:   flags.append("🟢смена")
        if u["is_manager"]: flags.append("👔мнг")
        if u["is_creator"]: flags.append("📝дрп")
        f = " ".join(flags) or "—"
        lines.append(
            f"• <b>{u['first_name'] or '—'}</b> "
            f"(@{u['username'] or '—'}) "
            f"[<code>{u['user_id']}</code>] {f}"
        )

    text = "\n".join(lines)
    # Telegram ограничивает сообщение ~4096 символами
    for chunk_start in range(0, len(text), 4000):
        await update.message.reply_text(
            text[chunk_start:chunk_start + 4000],
            parse_mode=ParseMode.HTML,
        )


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    s = db.get_stats()
    text = (
        "📊 <b>Статистика</b>\n\n"
        f"📦 Всего заявок: {s['total']}\n"
        f"✅ Взято: {s['taken']}\n"
        f"⏳ Активных: {s['active']}\n"
    )
    if s["top_takers"]:
        text += "\n🏆 <b>Топ:</b>\n"
        for i, t in enumerate(s["top_takers"], 1):
            text += f"  {i}. @{t['taken_by_username'] or '—'} — {t['cnt']}\n"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_taken(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    drops = db.get_taken_drops(20)
    if not drops:
        await update.message.reply_text("Нет взятых заявок.")
        return
    lines = ["📋 <b>Последние взятые заявки:</b>\n"]
    for d in drops:
        lines.append(
            f"• #{d['id']} {d['fio']} | {d['bank']} | "
            f"@{d['taken_by_username'] or '—'} | {d['taken_at'] or ''}"
        )
    await update.message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_active(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    drops = db.get_active_drops()
    if not drops:
        await update.message.reply_text("Нет активных заявок.")
        return
    lines = ["⏳ <b>Активные (не взятые) заявки:</b>\n"]
    for d in drops:
        lines.append(
            f"• #{d['id']} {d['fio']} | {d['bank']} | {d['created_at']}"
        )
    await update.message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.HTML)


# ═══════════════════════════════════════════════════════════
#  ConversationHandler — создание заявки (/new)
# ═══════════════════════════════════════════════════════════

async def cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Точка входа: только ЛС, только дроповоды/админы."""
    user = update.effective_user
    _register(user)

    if not _is_creator(user.id) and not _is_admin(user.id):
        await update.message.reply_text("⛔ Нет прав для создания заявок.")
        return -1  # ConversationHandler.END

    if update.effective_chat.type != "private":
        await update.message.reply_text(
            "⚠️ Создание заявок — только в ЛС с ботом.")
        return -1

    # Очищаем временное хранилище
    context.user_data["drop"] = {"photos": []}

    await update.message.reply_text(
        "📝 <b>Новая заявка</b>\n\n"
        "Шаг 1/9 · Пришлите <b>ФИО дропа</b>\n\n"
        "/cancel — отменить",
        parse_mode=ParseMode.HTML,
    )
    return ASK_FIO


# ── Шаг 1: ФИО ──

async def conv_fio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["drop"]["fio"] = update.message.text.strip()
    await update.message.reply_text(
        "💳 Шаг 2/9 · <b>Номер карты</b>",
        parse_mode=ParseMode.HTML)
    return ASK_CARD


# ── Шаг 2: Карта ──

async def conv_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["drop"]["card"] = update.message.text.strip()
    await update.message.reply_text(
        "🏦 Шаг 3/9 · <b>Номер счёта</b>",
        parse_mode=ParseMode.HTML)
    return ASK_ACCOUNT


# ── Шаг 3: Счёт ──

async def conv_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["drop"]["account"] = update.message.text.strip()
    await update.message.reply_text(
        "📱 Шаг 4/9 · <b>Номер телефона</b>",
        parse_mode=ParseMode.HTML)
    return ASK_PHONE


# ── Шаг 4: Телефон ──

async def conv_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["drop"]["phone"] = update.message.text.strip()
    await update.message.reply_text(
        "👤 Шаг 5/9 · <b>Юзернейм дропа</b> (@username или <b>-</b>)",
        parse_mode=ParseMode.HTML)
    return ASK_DROP_USERNAME


# ── Шаг 5: Юзернейм дропа ──

async def conv_drop_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["drop"]["drop_username"] = update.message.text.strip()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 Альфа-Банк", callback_data="bank_alfa")],
        [InlineKeyboardButton("🟡 СберБанк",   callback_data="bank_sber")],
        [InlineKeyboardButton("⚫ Т-Банк",      callback_data="bank_tbank")],
    ])
    await update.message.reply_text(
        "🏦 Шаг 6/9 · Выберите <b>банк</b>:",
        reply_markup=kb, parse_mode=ParseMode.HTML)
    return ASK_BANK


# ── Шаг 6: Банк (callback) ──

async def conv_bank_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    bank_map = {
        "bank_alfa":  "Альфа-Банк",
        "bank_sber":  "СберБанк",
        "bank_tbank": "Т-Банк",
    }
    context.user_data["drop"]["bank"] = bank_map.get(q.data, q.data)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Далее ➡️", callback_data="scr_done")]
    ])
    await q.edit_message_text(
        f"✅ Банк: <b>{context.user_data['drop']['bank']}</b>\n\n"
        "📸 Шаг 7/9 · Пришлите <b>скриншоты трат</b> "
        "(1-2 фото).\n"
        "После отправки нажмите <b>«Далее ➡️»</b>.",
        reply_markup=kb, parse_mode=ParseMode.HTML)
    return ASK_SCREENSHOTS


# ── Шаг 7: Скриншоты ──

async def conv_screenshot_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получено фото — сохраняем file_id."""
    photo = update.message.photo[-1]  # наилучшее качество
    context.user_data["drop"]["photos"].append(photo.file_id)
    n = len(context.user_data["drop"]["photos"])

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Далее ➡️", callback_data="scr_done")]
    ])
    await update.message.reply_text(
        f"📸 Фото #{n} сохранено. Ещё фото или <b>«Далее ➡️»</b>.",
        reply_markup=kb, parse_mode=ParseMode.HTML)
    return ASK_SCREENSHOTS


async def conv_screenshot_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not context.user_data["drop"]["photos"]:
        await q.answer("⚠️ Отправьте хотя бы одно фото!", show_alert=True)
        return ASK_SCREENSHOTS
    await q.answer()
    await q.edit_message_text(
        "🔗 Шаг 8/9 · Пришлите <b>ссылку на чат</b> с дропом.",
        parse_mode=ParseMode.HTML)
    return ASK_CHAT_LINK


# ── Шаг 8: Ссылка на чат ──

async def conv_chat_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["drop"]["chat_link"] = update.message.text.strip()
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Проверенный",   callback_data="ver_yes"),
        InlineKeyboardButton("❌ Непроверенный", callback_data="ver_no"),
    ]])
    await update.message.reply_text(
        "🔍 Шаг 9/9 · <b>Статус дропа</b>:",
        reply_markup=kb, parse_mode=ParseMode.HTML)
    return ASK_VERIFIED


# ── Шаг 9: Статус + публикация ──

async def conv_verified_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    verified = "✅ Проверенный" if q.data == "ver_yes" else "❌ Непроверенный"
    context.user_data["drop"]["verified"] = verified

    await q.edit_message_text("⏳ Публикую заявку в группу…")

    d = context.user_data["drop"]
    user = update.effective_user

    drop_id = db.create_drop(
        fio=d["fio"],
        card_number=d["card"],
        account_number=d["account"],
        phone=d["phone"],
        drop_username=d["drop_username"],
        bank=d["bank"],
        chat_link=d["chat_link"],
        verified=verified,
        creator_id=user.id,
        photo_file_ids=d["photos"],
    )

    await _publish_drop(context, drop_id, user)

    await q.edit_message_text(
        f"✅ Заявка <b>#{drop_id}</b> опубликована!",
        parse_mode=ParseMode.HTML)

    context.user_data.pop("drop", None)
    return -1  # ConversationHandler.END


async def conv_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("drop", None)
    await update.message.reply_text("❌ Создание заявки отменено.")
    return -1


# ═══════════════════════════════════════════════════════════
#  Публикация дропа в супергруппу
# ═══════════════════════════════════════════════════════════

async def _publish_drop(context: ContextTypes.DEFAULT_TYPE,
                        drop_id: int, creator):
    """
    Отправляет пост о дропе в супергруппу:
      • фото (одно или несколько)
      • текст с данными
      • InLine-кнопки «Перейти в чат» и «Принимаю»
    Затем запускает периодическое тегирование через JobQueue.
    """
    drop   = db.get_drop(drop_id)
    photos = db.get_drop_photos(drop_id)

    creator_mention = _mention(creator.id, creator.username, creator.first_name)
    chat_link = _ensure_https(drop["chat_link"])

    text = (
        f"🆕 <b>НОВЫЙ ДРОП В РАБОТУ!</b>  #{drop_id}\n\n"
        f"👤 Создал: {creator_mention}\n"
        f"🏦 Банк: <b>{drop['bank']}</b>\n"
        f"📊 Статус: <b>{drop['verified']}</b>\n"
        f"👤 Дроп: <b>{drop['fio']}</b>\n\n"
        f"🔗 <a href=\"{chat_link}\">Ссылка на чат с дропом</a>\n\n"
        f"<b>Данные дропа:</b>\n"
        f"💳 Карта: <code>{drop['card_number']}</code>\n"
        f"🏦 Счёт: <code>{drop['account_number']}</code>\n"
        f"📱 Тел: <code>{drop['phone']}</code>\n"
        f"👤 Юзер: {drop['drop_username']}"
    )

    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Перейти в чат", url=chat_link)],
        [InlineKeyboardButton("✅ Принимаю",
                              callback_data=f"take_{drop_id}")],
    ])

    group_msg_id = None
    btn_msg_id   = None

    if len(photos) == 1:
        # Одно фото — кнопки прямо под ним
        msg = await context.bot.send_photo(
            chat_id=SUPERGROUP_ID,
            photo=photos[0],
            caption=text,
            parse_mode=ParseMode.HTML,
            reply_markup=buttons,
        )
        group_msg_id = btn_msg_id = msg.message_id

    elif len(photos) > 1:
        # Медиагруппа: подпись на первом фото,
        # кнопки — отдельным сообщением-ответом
        media = [
            InputMediaPhoto(media=photos[0], caption=text,
                            parse_mode=ParseMode.HTML)
        ] + [InputMediaPhoto(media=fid) for fid in photos[1:]]

        msgs = await context.bot.send_media_group(
            chat_id=SUPERGROUP_ID, media=media)
        group_msg_id = msgs[0].message_id

        btn_msg = await context.bot.send_message(
            chat_id=SUPERGROUP_ID,
            text=f"👆 Заявка <b>#{drop_id}</b> — нажми кнопку:",
            reply_markup=buttons,
            parse_mode=ParseMode.HTML,
            reply_to_message_id=group_msg_id,
        )
        btn_msg_id = btn_msg.message_id

    else:
        # Нет фото — просто текст
        msg = await context.bot.send_message(
            chat_id=SUPERGROUP_ID,
            text=text,
            reply_markup=buttons,
            parse_mode=ParseMode.HTML,
        )
        group_msg_id = btn_msg_id = msg.message_id

    db.set_drop_message_ids(drop_id, group_msg_id, btn_msg_id)

    # ── Запуск периодического тегирования ──
    # first=10 — первый тег через 10 секунд после публикации
    context.job_queue.run_repeating(
        _job_tag,
        interval=TAG_INTERVAL_SECONDS,
        first=10,
        data={"drop_id": drop_id},
        name=f"tag_drop_{drop_id}",
    )
    logger.info("Drop #%s published, tagging job started.", drop_id)


# ═══════════════════════════════════════════════════════════
#  JobQueue — периодическое тегирование
# ═══════════════════════════════════════════════════════════

async def _job_tag(context: ContextTypes.DEFAULT_TYPE):
    """
    Повторяющаяся задача: тегирует всех «на смене» с интервалом,
    пока заявка не будет взята.
    """
    drop_id = context.job.data["drop_id"]

    drop = db.get_drop(drop_id)
    if drop is None or drop["is_taken"]:
        context.job.schedule_removal()
        return

    users = db.get_on_shift_users()
    if not users:
        return

    mentions = []
    for u in users:
        mentions.append(
            _mention(u["user_id"], u["username"], u["first_name"]))

    reply_to = drop["button_message_id"] or drop["group_message_id"]

    try:
        await context.bot.send_message(
            chat_id=SUPERGROUP_ID,
            text=(
                f"🔔 {' '.join(mentions)}\n\n"
                f"⚡ Заявка <b>#{drop_id}</b> ждёт! Кто возьмёт?"
            ),
            parse_mode=ParseMode.HTML,
            reply_to_message_id=reply_to,
        )
    except Exception as exc:
        logger.error("Tagging failed for drop #%s: %s", drop_id, exc)
        # Если сообщение удалено — шлём без reply
        try:
            await context.bot.send_message(
                chat_id=SUPERGROUP_ID,
                text=(
                    f"🔔 {' '.join(mentions)}\n\n"
                    f"⚡ Заявка <b>#{drop_id}</b> ждёт! Кто возьмёт?"
                ),
                parse_mode=ParseMode.HTML,
            )
        except Exception as exc2:
            logger.error("Tagging totally failed: %s", exc2)


# ═══════════════════════════════════════════════════════════
#  Callback «✅ Принимаю»
# ═══════════════════════════════════════════════════════════

async def cb_take_drop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    user = q.from_user
    _register(user)

    try:
        drop_id = int(q.data.split("_")[1])
    except (IndexError, ValueError):
        await q.answer("⚠️ Ошибка.", show_alert=True)
        return

    success = db.take_drop(
        drop_id, user.id, user.username or user.first_name)

    if not success:
        await q.answer("⚠️ Заявка уже взята!", show_alert=True)
        return

    await q.answer("✅ Вы приняли заявку!")

    drop = db.get_drop(drop_id)
    taker = _mention(user.id, user.username, user.first_name)
    chat_link = _ensure_https(drop["chat_link"])

    new_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Перейти в чат", url=chat_link)],
    ])

    # Обновляем сообщение с кнопками
    try:
        if drop["button_message_id"] == drop["group_message_id"]:
            # Кнопки были под фото / текстом — меняем только клавиатуру
            await context.bot.edit_message_reply_markup(
                chat_id=SUPERGROUP_ID,
                message_id=drop["button_message_id"],
                reply_markup=new_kb,
            )
            await context.bot.send_message(
                chat_id=SUPERGROUP_ID,
                text=(f"✅ Заявка <b>#{drop_id}</b> взята!\n"
                      f"👤 Ответственный: {taker}"),
                parse_mode=ParseMode.HTML,
                reply_to_message_id=drop["group_message_id"],
            )
        else:
            # Отдельное сообщение с кнопками — редактируем текст + клавиатуру
            await context.bot.edit_message_text(
                chat_id=SUPERGROUP_ID,
                message_id=drop["button_message_id"],
                text=(f"✅ Заявка <b>#{drop_id}</b> взята!\n"
                      f"👤 Ответственный: {taker}"),
                reply_markup=new_kb,
                parse_mode=ParseMode.HTML,
            )
    except Exception as exc:
        logger.error("Edit failed for drop #%s: %s", drop_id, exc)

    # Останавливаем тегирование
    for job in context.job_queue.get_jobs_by_name(f"tag_drop_{drop_id}"):
        job.schedule_removal()

    logger.info("Drop #%s taken by %s (@%s)", drop_id, user.id, user.username)

    # Уведомляем админов в ЛС (опционально)
    for aid in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=aid,
                text=(f"📌 Заявка <b>#{drop_id}</b> ({drop['fio']}) "
                      f"взята пользователем {taker}"),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass  # админ мог не начать диалог с ботом


# ═══════════════════════════════════════════════════════════
#  post_init — восстановление после перезапуска
# ═══════════════════════════════════════════════════════════

async def on_startup(application):
    """
    Вызывается после Application.initialize().
    Проверяет БД на наличие активных (не взятых) дропов
    и возобновляет для них задачи тегирования.
    """
    active = db.get_active_drops()
    for drop in active:
        application.job_queue.run_repeating(
            _job_tag,
            interval=TAG_INTERVAL_SECONDS,
            first=30,  # первая через 30 сек после старта
            data={"drop_id": drop["id"]},
            name=f"tag_drop_{drop['id']}",
        )
        logger.info("Resumed tagging for active drop #%s", drop["id"])
    logger.info("Startup complete. Active drops: %d", len(active))
