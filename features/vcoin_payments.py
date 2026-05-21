import html
import logging
import time
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, Message, ReplyKeyboardMarkup

from admins import ADMIN_IDS
from features.vcoin_backend import (
    VCoinBackendError,
    backend_enabled,
    confirm_payment,
    create_payment_request,
    get_balance,
    get_payment_intent,
    reject_payment,
)
from features.vcoin_config import (
    FULL_MOCK_COST,
    SEPARATE_BLOCK_COST,
    WEBSITE_WALLET_URL,
    build_payment_details_text,
    build_premiere_payment_details_text,
)


logger = logging.getLogger(__name__)
router = Router()


class VCoinBuyState(StatesGroup):
    receipt = State()


BUY_MODE_TIMEOUT_SECONDS = 30 * 60
CANCEL_TEXT = "Cancel"


def _cancel_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=CANCEL_TEXT)]],
        resize_keyboard=True,
    )


def _main_menu_keyboard():
    from features.ielts_checkup_ui import main_user_keyboard
    return main_user_keyboard()


def _now_ts() -> int:
    return int(time.time())


def _is_mode_expired(started_at: int | None) -> bool:
    if not started_at:
        return False
    return (_now_ts() - int(started_at)) > BUY_MODE_TIMEOUT_SECONDS


async def _exit_buy_mode(message: Message, state: FSMContext, text: str):
    await state.clear()
    await message.answer(text, reply_markup=_main_menu_keyboard())


def _admin_keyboard(payment_id: str):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Confirm", callback_data=f"vcoin_admin:confirm:{payment_id}"),
        InlineKeyboardButton(text="Reject", callback_data=f"vcoin_admin:reject:{payment_id}"),
    ]])


def _is_already_finalized(result) -> bool:
    status = str(result.get("status") or result.get("error") or "").lower()
    return bool(result.get("already_finalized")) or status in {
        "already_finalized",
        "payment_already_finalized",
        "expired",
    }


def _receipt_from_message(message: Message):
    if message.photo:
        photo = message.photo[-1]
        return {
            "file_type": "photo",
            "file_id": photo.file_id,
            "file_unique_id": photo.file_unique_id,
        }

    document = message.document
    if document:
        return {
            "file_type": "document",
            "file_id": document.file_id,
            "file_unique_id": document.file_unique_id,
            "mime_type": document.mime_type,
            "file_name": document.file_name,
        }

    return None


def _backend_unavailable_text():
    return (
        "Receipt received, but payment system is temporarily unavailable. "
        "Please try again or contact admin."
    )


def _backend_config_missing_text():
    return "Payment system is not fully configured yet. Please contact admin."


def _money(amount) -> str:
    try:
        return f"{int(amount):,}".replace(",", " ")
    except (TypeError, ValueError):
        return str(amount or "0")


def _normalize_payment_token(value: str) -> str:
    token = str(value or "").strip().upper()
    if token.startswith("PAY_"):
        token = token[4:]
    return token


def _payment_from_response(data):
    return data.get("payment") if isinstance(data, dict) else None


def _payment_status(payment) -> str:
    return str((payment or {}).get("status") or "").lower()


def _payment_is_open(payment) -> bool:
    return _payment_status(payment) in {"pending", "duplicate_suspected"}


def _payment_owner_id(payment):
    try:
        return int((payment or {}).get("telegram_id") or 0)
    except (TypeError, ValueError):
        return 0


def _is_premiere_payment(payment) -> bool:
    kind = str((payment or {}).get("payment_kind") or "").lower()
    package_code = str((payment or {}).get("package_code") or "").lower()
    return bool(
        kind == "premiere_access"
        or package_code == "premiere_access"
        or (payment or {}).get("mock_pack_id")
    )


def _payment_context_name(payment) -> str:
    return "Premiere" if _is_premiere_payment(payment) else "V-Coin"


def _payment_details_text(payment) -> str:
    if _is_premiere_payment(payment):
        return build_premiere_payment_details_text(payment)
    return build_payment_details_text(payment)


def _start_payload(message: Message) -> str:
    text = str(message.text or "").strip()
    parts = text.split(maxsplit=1)
    if not parts or not parts[0].startswith("/start") or len(parts) < 2:
        return ""
    return parts[1].strip()


def _admin_payment_text(payment_id, user, payment, receipt, status, submitted_at, backend_message="", duplicate=False):
    token = payment.get("payment_token") or "-"
    coins = payment.get("coins_to_add") or "-"
    is_premiere = _is_premiere_payment(payment)
    title = "Premiere access payment request" if is_premiere else "V-Coin payment request"
    subtotal = _money(payment.get("subtotal_amount"))
    discount = _money(payment.get("discount_amount"))
    final_amount = _money(payment.get("final_amount") or payment.get("expected_price") or 0)
    promo = payment.get("promo_code") or "-"

    lines = [
        f"<b>{title}</b>",
        "",
        f"<b>Payment ID:</b> <code>{html.escape(payment_id or 'unknown')}</code>",
        f"<b>Payment token:</b> <code>{html.escape(str(token))}</code>",
        f"<b>User telegram_id:</b> <code>{user.id}</code>",
        f"<b>Name:</b> {html.escape(user.full_name or '-')}",
        f"<b>Username:</b> @{html.escape(user.username or '-')}",
    ]
    if is_premiere:
        lines.extend([
            f"<b>Mock:</b> {html.escape(str(payment.get('mock_title') or 'Premiere Mock'))}",
            f"<b>Mock ID:</b> <code>{html.escape(str(payment.get('mock_pack_id') or '-'))}</code>",
        ])
    else:
        lines.extend([
            f"<b>Coins:</b> {html.escape(str(coins))} V-Coin",
            f"<b>Subtotal:</b> {html.escape(subtotal)} UZS",
            f"<b>Promo:</b> {html.escape(str(promo))}",
            f"<b>Discount:</b> {html.escape(discount)} UZS",
        ])
    lines.extend([
        f"<b>Expected amount:</b> {html.escape(final_amount)} UZS",
        f"<b>Backend status:</b> {html.escape(str(status))}",
        f"<b>Duplicate flag:</b> {'yes' if duplicate else 'no'}",
        f"<b>Receipt file_id:</b> <code>{html.escape(receipt['file_id'])}</code>",
        f"<b>Receipt hash:</b> <code>{html.escape(receipt.get('file_unique_id') or '-')}</code>",
        f"<b>Submitted at:</b> <code>{html.escape(submitted_at)}</code>",
    ])
    if backend_message:
        lines.append(f"<b>Message:</b> {html.escape(str(backend_message))}")
    return "\n".join(lines)


async def _send_admin_receipt(
    message: Message,
    payment_id,
    payment,
    receipt,
    status,
    submitted_at,
    backend_message="",
    duplicate=False,
):
    admin_text = _admin_payment_text(
        payment_id=payment_id,
        user=message.from_user,
        payment=payment,
        receipt=receipt,
        status=status,
        submitted_at=submitted_at,
        backend_message=backend_message,
        duplicate=duplicate,
    )

    for admin_id in ADMIN_IDS:
        try:
            if receipt["file_type"] == "document":
                await message.bot.send_document(
                    chat_id=admin_id,
                    document=receipt["file_id"],
                    caption=admin_text,
                    reply_markup=_admin_keyboard(payment_id) if payment_id else None,
                    parse_mode="HTML",
                )
            else:
                await message.bot.send_photo(
                    chat_id=admin_id,
                    photo=receipt["file_id"],
                    caption=admin_text,
                    reply_markup=_admin_keyboard(payment_id) if payment_id else None,
                    parse_mode="HTML",
                )
        except Exception:
            logger.exception("Failed to notify admin %s about V-Coin payment", admin_id)


async def _mark_admin_message(cb: CallbackQuery, text: str):
    try:
        if cb.message.caption:
            await cb.message.edit_caption(
                caption=f"{cb.message.caption}\n\n{text}",
                parse_mode="HTML",
                reply_markup=None,
            )
        else:
            await cb.message.edit_text(
                f"{cb.message.text or ''}\n\n{text}",
                parse_mode="HTML",
                reply_markup=None,
            )
    except Exception:
        await cb.message.answer(text, parse_mode="HTML")


@router.message(Command("vcoins"))
async def vcoin_balance(message: Message):
    if not backend_enabled():
        await message.answer("V-Coin backend URL/token is not configured yet.")
        return

    try:
        data = await get_balance(message.from_user.id)
    except VCoinBackendError as exc:
        await message.answer(f"Could not load V-Coin balance: {exc}")
        return

    balance = data.get("balance", 0)
    await message.answer(
        "V-Coin balance\n\n"
        f"Balance: {balance} V-Coin\n"
        f"Full Mock: {FULL_MOCK_COST} V-Coin\n"
        f"Separate block: {SEPARATE_BLOCK_COST} V-Coin"
    )


@router.message(Command("buy_vcoin"))
@router.message(F.text.in_({"Buy V-Coin", "V-Coin", "Buy VCoin", "💳 Buy V-Coin"}))
async def buy_vcoin(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "<b>Buy V-Coin on the website</b>\n\n"
        "Choose any V-Coin amount, apply promo codes, and then return here with the payment link.\n\n"
        f"<a href=\"{html.escape(WEBSITE_WALLET_URL)}\">Open EBAI Academy wallet</a>",
        parse_mode="HTML",
    )


async def start_payment_token(message: Message, state: FSMContext, payment_token: str):
    token = _normalize_payment_token(payment_token)
    if not token:
        await message.answer("Payment link is invalid. Please create a new payment from the website wallet.")
        return

    if not backend_enabled():
        await message.answer(_backend_config_missing_text())
        return

    try:
        response = await get_payment_intent(token)
        payment = _payment_from_response(response)
    except VCoinBackendError as exc:
        logger.warning("Could not fetch V-Coin payment intent %s: %s", token, exc)
        await message.answer("Payment request was not found or has expired. Please create a new payment from the website wallet.")
        return

    if not payment:
        await message.answer("Payment request could not be loaded. Please create a new payment from the website wallet.")
        return

    owner_id = _payment_owner_id(payment)
    if owner_id and owner_id != int(message.from_user.id):
        await message.answer("This payment link belongs to another Telegram account.")
        return
    if not owner_id and not _is_premiere_payment(payment):
        await message.answer("This payment link is missing Telegram account information. Please create a new payment from the website wallet.")
        return

    if not _payment_is_open(payment):
        await message.answer(
            "This payment request is no longer active.\n\n"
            f"Status: {_payment_status(payment) or 'unknown'}"
        )
        return

    await state.clear()
    await state.set_state(VCoinBuyState.receipt)
    await state.update_data(
        buy_started_at=_now_ts(),
        receipt_started_at=_now_ts(),
        payment_token=token,
        payment=payment,
    )

    await message.answer(
        _payment_details_text(payment),
        reply_markup=_cancel_keyboard(),
        parse_mode="HTML",
    )


@router.message(VCoinBuyState.receipt, F.photo | F.document)
async def receive_receipt(message: Message, state: FSMContext):
    data = await state.get_data()
    started_at = data.get("receipt_started_at") or data.get("buy_started_at")
    if _is_mode_expired(started_at):
        context = _payment_context_name(data.get("payment") or {})
        await _exit_buy_mode(
            message,
            state,
            f"{context} payment mode expired after 30 minutes. Please reopen the payment from the website.",
        )
        return

    payment_token = data.get("payment_token")
    payment = data.get("payment") or {}
    if not payment_token or not payment:
        await _exit_buy_mode(
            message,
            state,
            "Payment context is missing. Please reopen the payment from the website.",
        )
        return

    receipt = _receipt_from_message(message)
    if not receipt:
        await message.answer("Please send the receipt/check as a screenshot photo or document.")
        return

    if not backend_enabled():
        await _exit_buy_mode(message, state, _backend_config_missing_text())
        return

    submitted_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "telegram_id": message.from_user.id,
        "payment_token": payment_token,
        "username": message.from_user.username,
        "first_name": message.from_user.first_name,
        "full_name": message.from_user.full_name,
        "receipt_file_type": receipt["file_type"],
        "receipt_file_id": receipt["file_id"],
        "receipt_image_hash": receipt.get("file_unique_id"),
        "receipt_mime_type": receipt.get("mime_type"),
        "receipt_file_name": receipt.get("file_name"),
        "submitted_at": submitted_at,
        "source": "telegram_bot_premiere_payment_token" if _is_premiere_payment(payment) else "telegram_bot_payment_token",
    }

    try:
        created = await create_payment_request(payload)
    except VCoinBackendError as exc:
        logger.warning("V-Coin receipt submission failed: %s", exc)
        await _exit_buy_mode(message, state, _backend_unavailable_text())
        return

    payment_id = str(created.get("payment_id") or created.get("id") or "")
    status = created.get("status", "pending")
    backend_message = created.get("message", "")
    duplicate = bool(created.get("duplicate") or created.get("duplicate_suspected") or status == "duplicate_suspected")

    await _exit_buy_mode(
        message,
        state,
        f"{_payment_context_name(payment)} receipt received. We are checking your payment.\n\n"
        f"Status: {status}"
    )

    await _send_admin_receipt(
        message=message,
        payment_id=payment_id,
        payment=payment,
        receipt=receipt,
        status=status,
        submitted_at=submitted_at,
        backend_message=backend_message,
        duplicate=duplicate,
    )


@router.message(VCoinBuyState.receipt, ~F.text.in_({CANCEL_TEXT}), ~F.text.startswith("/"))
async def receipt_must_be_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    started_at = data.get("receipt_started_at") or data.get("buy_started_at")
    if _is_mode_expired(started_at):
        context = _payment_context_name(data.get("payment") or {})
        await _exit_buy_mode(
            message,
            state,
            f"{context} payment mode expired after 30 minutes. Please reopen the payment from the website.",
        )
        return
    await message.answer("Please send the receipt/check as a screenshot photo or document.")


@router.message(F.text == CANCEL_TEXT, VCoinBuyState.receipt)
@router.message(Command("cancel"), VCoinBuyState.receipt)
async def cancel_vcoin_buy(message: Message, state: FSMContext):
    data = await state.get_data()
    context = _payment_context_name(data.get("payment") or {})
    await _exit_buy_mode(message, state, f"{context} payment cancelled.")


@router.message(VCoinBuyState.receipt, F.text.startswith("/"))
async def receipt_mode_command_escape(message: Message, state: FSMContext):
    payload = _start_payload(message)
    if payload.startswith("pay_"):
        await start_payment_token(message, state, payload)
        return
    await _exit_buy_mode(
        message,
        state,
        "Payment flow cancelled. Send your command again now.",
    )


@router.message(F.photo | F.document)
async def receipt_without_package(message: Message):
    await message.answer("Please create a V-Coin payment from the website wallet first.")


@router.callback_query(F.data.startswith("vcoin_confirm:"))
async def admin_confirm_vcoin(cb: CallbackQuery):
    payment_id = cb.data.split(":", 1)[1]
    await _admin_payment_action(cb, payment_id, "confirm")


@router.callback_query(F.data.startswith("vcoin_reject:"))
async def admin_reject_vcoin(cb: CallbackQuery):
    payment_id = cb.data.split(":", 1)[1]
    await _admin_payment_action(cb, payment_id, "reject")


@router.callback_query(F.data.startswith("vcoin_admin:"))
async def admin_vcoin_action(cb: CallbackQuery):
    parts = cb.data.split(":", 2)
    if len(parts) != 3:
        await cb.answer("Old or invalid button.", show_alert=True)
        return
    await _admin_payment_action(cb, parts[2], parts[1])


async def _admin_payment_action(cb: CallbackQuery, payment_id: str, action: str):
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("Admins only.", show_alert=True)
        return

    if not payment_id:
        await cb.answer("Missing payment ID.", show_alert=True)
        return

    try:
        if action == "confirm":
            result = await confirm_payment(payment_id, cb.from_user.id)
        elif action == "reject":
            result = await reject_payment(payment_id, cb.from_user.id, reason="admin_rejected")
        else:
            await cb.answer("Unknown action.", show_alert=True)
            return
    except VCoinBackendError as exc:
        await cb.answer("Backend error.", show_alert=True)
        await cb.message.answer(f"{action.title()} failed: {html.escape(str(exc))}")
        return

    status = result.get("status", "unknown")
    if _is_already_finalized(result):
        await cb.answer("Payment is already finalized.", show_alert=True)
    else:
        await cb.answer(f"{action.title()} sent.")

    if action == "confirm":
        access_text = "Premiere access granted" if result.get("premiere_access") else "V-Coins added"
        await _mark_admin_message(
            cb,
            f"<b>Status:</b> confirmed signal sent for <code>{html.escape(payment_id)}</code>\n"
            f"<b>Result:</b> {html.escape(access_text)}\n"
            f"<b>Backend:</b> {html.escape(str(status))}",
        )
    else:
        await _mark_admin_message(
            cb,
            f"<b>Status:</b> rejected signal sent for <code>{html.escape(payment_id)}</code>\n"
            f"<b>Backend:</b> {html.escape(str(status))}",
        )

    user_id = result.get("telegram_id")
    if user_id:
        try:
            if action == "confirm":
                if result.get("premiere_access"):
                    text = "Payment confirmed. Your Premiere Mock access has been unlocked."
                else:
                    text = "Payment confirmed. Your V-Coins have been added."
                await cb.bot.send_message(
                    chat_id=user_id,
                    text=text,
                )
            else:
                await cb.bot.send_message(
                    chat_id=user_id,
                    text="Payment could not be confirmed. Please contact admin or send a clearer receipt.",
                )
        except Exception:
            logger.exception("Failed to notify user %s about V-Coin %s", user_id, action)
