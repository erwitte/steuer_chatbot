"""Telegram layer: thin handlers that parse updates and call into the service layer."""

import asyncio
import logging
import mimetypes
import shutil
import tempfile
import warnings
from dataclasses import dataclass
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
from steuer_chatbot.parsing import parse_commute_distance_km, parse_cost_cents, parse_entry_date
from steuer_chatbot.settings import get_commute_distance, set_commute_distance

log = logging.getLogger(__name__)

# The flow mixes message and callback-query states, so per_message=False is intended.
warnings.filterwarnings("ignore", message=".*per_message=False.*", category=PTBUserWarning)

CHOOSING_CATEGORY, AWAITING_RECEIPT, AWAITING_COST, AWAITING_DATE, CONFIRMING = range(5)


@dataclass(frozen=True)
class CategoryPrompts:
    label: str
    date_question: str
    # Only Categories with a cost and a Receipt are asked for a cost.
    cost_question: str | None = None


RECEIPT_DATE_QUESTION = "Von welchem Datum ist der Beleg?"
CATEGORY_PROMPTS = {
    Category.HOMEOFFICE_PAUSCHALE: CategoryPrompts(
        label="Homeoffice-Pauschale",
        date_question="An welchem Tag hast du im Homeoffice gearbeitet?",
    ),
    Category.PENDLERPAUSCHALE: CategoryPrompts(
        label="Pendlerpauschale",
        date_question="An welchem Tag bist du ins Büro gependelt?",
    ),
    Category.WEITERBILDUNG: CategoryPrompts(
        label="Weiterbildung",
        date_question=RECEIPT_DATE_QUESTION,
        # One lump cost per Weiterbildung Entry, not itemized (ADR-0001).
        cost_question=(
            "Wie hoch waren die Gesamtkosten in Euro"
            " (Kursgebühr, Fahrt, Hotel und Verpflegung zusammen)? (z. B. 890,00)"
        ),
    ),
    Category.ARBEITSMITTEL: CategoryPrompts(
        label="Arbeitsmittel",
        date_question=RECEIPT_DATE_QUESTION,
        cost_question="Wie hoch waren die Kosten in Euro? (z. B. 49,99)",
    ),
}
DATE_FORMAT_HINT = "(JJJJ-MM-TT oder TT.MM.JJJJ)"
assert set(CATEGORY_PROMPTS) == set(Category) and all(
    (prompts.cost_question is not None) == category.has_cost_and_receipt
    for category, prompts in CATEGORY_PROMPTS.items()
), "CATEGORY_PROMPTS must cover every Category and ask for a cost exactly when it has one"

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
        [[InlineKeyboardButton(prompts.label, callback_data=f"category:{category}")]
         for category, prompts in CATEGORY_PROMPTS.items()]
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
    label = CATEGORY_PROMPTS[category].label

    await query.answer()
    if category.requires_commute_distance:
        try:
            commute_distance = await asyncio.to_thread(_load_commute_distance, _config(context))
        except Exception:
            log.exception("Loading Commute Distance failed")
            _reset_flow(context)
            await query.edit_message_text("Datenbank nicht erreichbar. Bitte später mit /start erneut versuchen.")
            return ConversationHandler.END
        if commute_distance is None:
            _reset_flow(context)
            await query.edit_message_text(
                f"{label}: Bitte lege zuerst deine Pendelstrecke (Hin- und Rückweg) fest,"
                " z. B. /setdistance 42 – und starte dann mit /start neu."
            )
            return ConversationHandler.END

    context.user_data["category"] = category
    if not category.has_cost_and_receipt:
        # Flat-rate Categories go straight to the date: no Receipt, no cost.
        await query.edit_message_text(f"{label}: {_date_question(category)}")
        return AWAITING_DATE

    await query.edit_message_text(f"{label}: Bitte sende den Beleg als Foto oder PDF.")
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

    category: Category = context.user_data["category"]
    await message.reply_text(f"Beleg erhalten. {_cost_question(category)}")
    return AWAITING_COST


async def receive_cost(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    assert message is not None and message.text is not None and context.user_data is not None
    category: Category = context.user_data["category"]
    try:
        context.user_data["cost_cents"] = parse_cost_cents(message.text)
    except ValueError:
        await message.reply_text(f"Das ist kein gültiger Betrag. {_cost_question(category)}")
        return AWAITING_COST
    await message.reply_text(_date_question(category))
    return AWAITING_DATE


async def receive_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    assert message is not None and message.text is not None and context.user_data is not None
    category: Category = context.user_data["category"]
    try:
        entry_date = parse_entry_date(message.text)
    except ValueError:
        await message.reply_text(f"Das ist kein gültiges Datum. {_date_question(category)}")
        return AWAITING_DATE
    context.user_data["entry_date"] = entry_date

    cost_line = ""
    if category.has_cost_and_receipt:
        cost_line = f"Kosten: {_format_euros(context.user_data['cost_cents'])}\n"
    keyboard = InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("Speichern", callback_data="confirm:save"),
            InlineKeyboardButton("Abbrechen", callback_data="confirm:cancel"),
        ]]
    )
    await message.reply_text(
        f"{CATEGORY_PROMPTS[category].label}\n"
        f"{cost_line}"
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


async def set_distance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    assert message is not None
    try:
        km = parse_commute_distance_km(" ".join(context.args or []))
    except ValueError:
        await message.reply_text(
            "Bitte gib deine Pendelstrecke (Hin- und Rückweg) in km an, z. B. /setdistance 42"
        )
        return

    try:
        await asyncio.to_thread(_store_commute_distance, _config(context), km)
    except Exception:
        log.exception("Saving Commute Distance failed")
        await message.reply_text("Speichern fehlgeschlagen. Bitte später erneut versuchen.")
        return
    km_text = f"{km:g}".replace(".", ",")
    await message.reply_text(f"Pendelstrecke gespeichert: {km_text} km (Hin- und Rückweg).")


def _load_commute_distance(config: Config) -> float | None:
    with psycopg.connect(config.database_url) as conn:
        return get_commute_distance(conn)


def _store_commute_distance(config: Config, km: float) -> None:
    with psycopg.connect(config.database_url) as conn:
        set_commute_distance(conn, km)


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


def _date_question(category: Category) -> str:
    return f"{CATEGORY_PROMPTS[category].date_question} {DATE_FORMAT_HINT}"


def _cost_question(category: Category) -> str:
    cost_question = CATEGORY_PROMPTS[category].cost_question
    assert cost_question is not None, f"{category} has no cost"
    return cost_question


def _format_euros(cents: int) -> str:
    return f"{cents // 100},{cents % 100:02d} €"


def build_application(config: Config) -> Application:  # type: ignore[type-arg]
    application = Application.builder().token(config.telegram_bot_token).build()
    application.bot_data["config"] = config

    application.add_handler(TypeHandler(Update, gate), group=-1)
    # Registered before the guided flow so it also works while a flow is in progress.
    application.add_handler(CommandHandler("setdistance", set_distance))
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
