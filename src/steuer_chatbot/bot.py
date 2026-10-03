"""Telegram layer: thin handlers that parse updates and call into the service layer."""

import asyncio
import logging
import mimetypes
import shutil
import tempfile
import warnings
from datetime import date
from pathlib import Path

import psycopg
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.warnings import PTBUserWarning
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    TypeHandler,
    filters,
)

from steuer_chatbot.config import Config
from steuer_chatbot.entries import Category, Entry, create_entry
from steuer_chatbot.parsing import parse_cost_cents, parse_entry_date

log = logging.getLogger(__name__)

# The flow mixes message and callback-query states, so per_message=False is intended.
warnings.filterwarnings("ignore", message=".*per_message=False.*", category=PTBUserWarning)

CHOOSING_CATEGORY, AWAITING_RECEIPT, AWAITING_COST, AWAITING_DATE, CONFIRMING = range(5)

CATEGORY_LABELS = {
    Category.HOMEOFFICE_PAUSCHALE: "Homeoffice-Pauschale",
    Category.PENDLERPAUSCHALE: "Pendlerpauschale",
    Category.WEITERBILDUNG: "Weiterbildung",
    Category.ARBEITSMITTEL: "Arbeitsmittel",
}
# Categories with a working guided flow; the others are built in later tickets.
IMPLEMENTED_CATEGORIES = {Category.ARBEITSMITTEL}

CANCELLED_TEXT = "Abgebrochen. Nichts wurde gespeichert."
STALE_BUTTON_TEXT = "Dieser Button ist nicht mehr aktiv."
# An abandoned flow is ended (and its staged Receipt discarded) after this many seconds.
FLOW_TIMEOUT_SECONDS = 60 * 60

# Incoming Receipts are staged inside RECEIPTS_DIR so the final move is a same-filesystem rename.
INCOMING_DIRNAME = ".incoming"


def _config(context: ContextTypes.DEFAULT_TYPE) -> Config:
    config: Config = context.bot_data["config"]
    return config


async def gate(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Drop every update not sent by the allowed user, before any other handler runs."""
    user = update.effective_user if isinstance(update, Update) else None
    if user is None or user.id != _config(context).allowed_telegram_user_id:
        raise ApplicationHandlerStop


def _discard_receipt(context: ContextTypes.DEFAULT_TYPE) -> None:
    user_data = context.user_data
    if user_data is None:
        return
    staging_dir = user_data.pop("receipt_staging_dir", None)
    if staging_dir is not None:
        shutil.rmtree(staging_dir, ignore_errors=True)


def _reset_flow(context: ContextTypes.DEFAULT_TYPE) -> None:
    _discard_receipt(context)
    if context.user_data is not None:
        context.user_data.clear()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    assert update.effective_message is not None
    _reset_flow(context)
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(label, callback_data=f"category:{category}")]
         for category, label in CATEGORY_LABELS.items()]
    )
    await update.effective_message.reply_text(
        "Welche Kategorie möchtest du erfassen? (/cancel zum Abbrechen)",
        reply_markup=keyboard,
    )
    return CHOOSING_CATEGORY


async def choose_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    assert query is not None and query.data is not None and context.user_data is not None
    category = Category(query.data.removeprefix("category:"))
    if category not in IMPLEMENTED_CATEGORIES:
        await query.answer(f"{CATEGORY_LABELS[category]} ist noch nicht verfügbar.", show_alert=True)
        return CHOOSING_CATEGORY

    await query.answer()
    context.user_data["category"] = category
    await query.edit_message_text(
        f"{CATEGORY_LABELS[category]}: Bitte sende den Beleg als Foto oder PDF."
    )
    return AWAITING_RECEIPT


async def receive_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    assert message is not None and context.user_data is not None
    if message.photo:
        telegram_file = await message.photo[-1].get_file()
        suffix = ".jpg"
    else:
        document = message.document
        assert document is not None
        telegram_file = await document.get_file()
        suffix = Path(document.file_name or "").suffix.lower() or (
            mimetypes.guess_extension(document.mime_type or "") or ""
        )

    _discard_receipt(context)
    incoming = _config(context).receipts_dir / INCOMING_DIRNAME
    incoming.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(tempfile.mkdtemp(dir=incoming))
    context.user_data["receipt_staging_dir"] = staging_dir
    receipt_path = staging_dir / f"receipt{suffix}"
    await telegram_file.download_to_drive(receipt_path)
    context.user_data["receipt"] = receipt_path

    await message.reply_text("Beleg erhalten. Wie hoch waren die Kosten in Euro? (z. B. 49,99)")
    return AWAITING_COST


async def receive_cost(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    assert message is not None and message.text is not None and context.user_data is not None
    try:
        context.user_data["cost_cents"] = parse_cost_cents(message.text)
    except ValueError:
        await message.reply_text("Das ist kein gültiger Betrag. Bitte z. B. 49,99 eingeben.")
        return AWAITING_COST
    await message.reply_text("Von welchem Datum ist der Beleg? (JJJJ-MM-TT oder TT.MM.JJJJ)")
    return AWAITING_DATE


async def receive_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    assert message is not None and message.text is not None and context.user_data is not None
    try:
        entry_date = parse_entry_date(message.text)
    except ValueError:
        await message.reply_text("Das ist kein gültiges Datum. Bitte JJJJ-MM-TT oder TT.MM.JJJJ eingeben.")
        return AWAITING_DATE
    context.user_data["entry_date"] = entry_date

    category: Category = context.user_data["category"]
    cost_cents: int = context.user_data["cost_cents"]
    keyboard = InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("Speichern", callback_data="confirm:save"),
            InlineKeyboardButton("Abbrechen", callback_data="confirm:cancel"),
        ]]
    )
    await message.reply_text(
        f"{CATEGORY_LABELS[category]}\n"
        f"Kosten: {_format_euros(cost_cents)}\n"
        f"Datum: {entry_date:%d.%m.%Y} (Steuerjahr {entry_date.year})\n\n"
        "Speichern?",
        reply_markup=keyboard,
    )
    return CONFIRMING


async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    assert query is not None and context.user_data is not None
    await query.answer()
    if query.data != "confirm:save":
        _reset_flow(context)
        await query.edit_message_text(CANCELLED_TEXT)
        return ConversationHandler.END

    config = _config(context)
    user_data = context.user_data
    try:
        entry = await asyncio.to_thread(
            _save_entry,
            config,
            user_data["category"],
            user_data["entry_date"],
            user_data.get("cost_cents"),
            user_data.get("receipt"),
        )
    except Exception:
        log.exception("Saving Entry failed")
        await query.edit_message_text("Speichern fehlgeschlagen. Bitte mit /start erneut versuchen.")
    else:
        await query.edit_message_text(
            f"Gespeichert als Eintrag #{entry.id} (Steuerjahr {entry.tax_year})."
        )
    finally:
        _reset_flow(context)
    return ConversationHandler.END


def _save_entry(
    config: Config,
    category: Category,
    entry_date: date,
    cost_cents: int | None,
    receipt: Path | None,
) -> Entry:
    with psycopg.connect(config.database_url) as conn:
        return create_entry(
            conn,
            config.receipts_dir,
            category=category,
            entry_date=entry_date,
            cost_cents=cost_cents,
            receipt_source_path=receipt,
        )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    assert update.effective_message is not None
    _reset_flow(context)
    await update.effective_message.reply_text(CANCELLED_TEXT)
    return ConversationHandler.END


async def timed_out(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    _reset_flow(context)


async def unexpected_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is not None:
        await update.callback_query.answer(STALE_BUTTON_TEXT)
        return
    assert update.effective_message is not None
    await update.effective_message.reply_text(
        "Das passt gerade nicht. Bitte beantworte die letzte Frage oder brich mit /cancel ab."
    )


async def outside_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is not None:
        await update.callback_query.answer(STALE_BUTTON_TEXT)
        return
    assert update.effective_message is not None
    await update.effective_message.reply_text("Starte eine neue Erfassung mit /start.")


def _format_euros(cents: int) -> str:
    return f"{cents // 100},{cents % 100:02d} €"


def build_application(config: Config) -> Application:  # type: ignore[type-arg]
    application = Application.builder().token(config.telegram_bot_token).build()
    application.bot_data["config"] = config

    application.add_handler(TypeHandler(Update, gate), group=-1)
    application.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler(["start", "new"], start)],
            states={
                CHOOSING_CATEGORY: [CallbackQueryHandler(choose_category, pattern=r"^category:")],
                AWAITING_RECEIPT: [
                    MessageHandler(
                        filters.PHOTO | filters.Document.PDF | filters.Document.IMAGE,
                        receive_receipt,
                    )
                ],
                AWAITING_COST: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_cost)],
                AWAITING_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_date)],
                CONFIRMING: [CallbackQueryHandler(confirm, pattern=r"^confirm:")],
                ConversationHandler.TIMEOUT: [TypeHandler(Update, timed_out)],
            },
            fallbacks=[
                CommandHandler("cancel", cancel),
                CommandHandler(["start", "new"], start),
                MessageHandler(filters.ALL, unexpected_input),
                CallbackQueryHandler(unexpected_input),
            ],
            conversation_timeout=FLOW_TIMEOUT_SECONDS,
        )
    )
    application.add_handler(MessageHandler(filters.ALL, outside_flow))
    application.add_handler(CallbackQueryHandler(outside_flow))
    return application
