"""
Точка входа. Собирает Application, регистрирует обработчики, запускает polling.
"""

import logging
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    filters,
)

from config import BOT_TOKEN
from handlers import (
    # Общие
    cmd_start, cmd_help,
    # Смена
    cmd_allstart, cmd_allstop,
    # Админ
    cmd_add_manager, cmd_remove_manager,
    cmd_add_creator, cmd_remove_creator,
    cmd_users, cmd_stats, cmd_taken, cmd_active,
    # Создание заявки (conversation)
    cmd_new,
    conv_fio, conv_card, conv_account, conv_phone,
    conv_drop_username, conv_bank_cb,
    conv_screenshot_photo, conv_screenshot_done,
    conv_chat_link, conv_verified_cb, conv_cancel,
    # Callback
    cb_take_drop,
    # Startup
    on_startup,
    # Состояния
    ASK_FIO, ASK_CARD, ASK_ACCOUNT, ASK_PHONE,
    ASK_DROP_USERNAME, ASK_BANK, ASK_SCREENSHOTS,
    ASK_CHAT_LINK, ASK_VERIFIED,
)

logging.basicConfig(
    format="%(asctime)s | %(name)-18s | %(levelname)-7s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main():
    # ── Сборка Application ──
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(on_startup)      # восстановление после рестарта
        .build()
    )

    # ── ConversationHandler: пошаговое создание заявки ──
    conv = ConversationHandler(
        entry_points=[CommandHandler("new", cmd_new)],
        states={
            ASK_FIO:          [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_fio)],
            ASK_CARD:         [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_card)],
            ASK_ACCOUNT:      [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_account)],
            ASK_PHONE:        [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_phone)],
            ASK_DROP_USERNAME:[MessageHandler(filters.TEXT & ~filters.COMMAND, conv_drop_username)],
            ASK_BANK:         [CallbackQueryHandler(conv_bank_cb, pattern=r"^bank_")],
            ASK_SCREENSHOTS:  [
                MessageHandler(filters.PHOTO, conv_screenshot_photo),
                CallbackQueryHandler(conv_screenshot_done, pattern=r"^scr_done$"),
            ],
            ASK_CHAT_LINK:    [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_chat_link)],
            ASK_VERIFIED:     [CallbackQueryHandler(conv_verified_cb, pattern=r"^ver_")],
        },
        fallbacks=[CommandHandler("cancel", conv_cancel)],
        per_user=True,
        per_chat=True,
    )

    # Важно: ConversationHandler регистрируется ПЕРВЫМ,
    # чтобы иметь приоритет над общими обработчиками
    app.add_handler(conv)

    # ── Общие команды ──
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help",  cmd_help))

    # ── Смена ──
    app.add_handler(CommandHandler("allstart", cmd_allstart))
    app.add_handler(CommandHandler("allstop",  cmd_allstop))

    # ── Админ ──
    app.add_handler(CommandHandler("add_manager",    cmd_add_manager))
    app.add_handler(CommandHandler("remove_manager", cmd_remove_manager))
    app.add_handler(CommandHandler("add_creator",    cmd_add_creator))
    app.add_handler(CommandHandler("remove_creator", cmd_remove_creator))
    app.add_handler(CommandHandler("users",  cmd_users))
    app.add_handler(CommandHandler("stats",  cmd_stats))
    app.add_handler(CommandHandler("taken",  cmd_taken))
    app.add_handler(CommandHandler("active", cmd_active))

    # ── Callback: «Принимаю» ──
    app.add_handler(CallbackQueryHandler(cb_take_drop, pattern=r"^take_\d+$"))

    # ── Запуск ──
    logger.info("🚀 Бот запускается…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
