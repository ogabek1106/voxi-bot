import html
import logging
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from admins import ADMIN_IDS
from features.vcoin_backend import (
    VCoinBackendError,
    backend_enabled,
    confirm_payment,
    create_payment_request,
    get_balance,
    reject_payment,
)
from features.vcoin_config import (
    FULL_MOCK_COST,
    SEPARATE_BLOCK_COST,
    build_payment_details_text,
    build_vcoin_packages_text,
    get_package,
    get_packages,
)


logger = logging.getLogger(__name__)
router = Router()


class VCoinBuyState(StatesGroup):
    receipt = State()


def _packages_keyboard():
    rows = []
    for package in get_packages():
        suffix = ""
        if package["code"] == "p20":
            suffix = " ⭐"
        elif package["code"] == "p30":
            suffix = " 🔥"

        rows.append([
            InlineKeyboardButton(
                text=f'{package["coins"]} V-Coins{suffix}',
                callback_data=f'vcoin_pkg:{package["code"]}',
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


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


def _admin_payment_text(payment_id, user, package, receipt, status, submitted_at, backend_message="", duplicate=False):
    lines = [
        "<b>V-Coin payment request</b>",
        "",
        f"<b>Payment ID:</b> <code>{html.escape(payment_id or 'unknown')}</code>",
        f"<b>User telegram_id:</b> <code>{user.id}</code>",
        f"<b>Name:</b> {html.escape(user.full_name or '-')}",
        f"<b>Username:</b> @{html.escape(user.username or '-')}",
        f"<b>Package:</b> {html.escape(package['code'])}",
        f"<b>Coins:</b> {package['coins']} V-Coin",
        f"<b>Price:</b> {html.escape(str(package['price']))}",
        f"<b>Backend status:</b> {html.escape(str(status))}",
        f"<b>Duplicate flag:</b> {'yes' if duplicate else 'no'}",
        f"<b>Receipt file_id:</b> <code>{html.escape(receipt['file_id'])}</code>",
        f"<b>Receipt hash:</b> <code>{html.escape(receipt.get('file_unique_id') or '-')}</code>",
        f"<b>Submitted at:</b> <code>{html.escape(submitted_at)}</code>",
    ]
    if backend_message:
        lines.append(f"<b>Message:</b> {html.escape(str(backend_message))}")
    return "\n".join(lines)


async def _send_admin_receipt(
    message: Message,
    payment_id,
    package,
    receipt,
    status,
    submitted_at,
    backend_message="",
    duplicate=False,
):
    admin_text = _admin_payment_text(
        payment_id=payment_id,
        user=message.from_user,
        package=package,
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
@router.message(F.text.in_({"💳 Buy V-Coin", "Buy V-Coin", "V-Coin", "Buy VCoin"}))
async def buy_vcoin(message: Message, state: FSMContext):
    await state.clear()
    text = build_vcoin_packages_text()
    await message.answer(
        text,
        reply_markup=_packages_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("vcoin_pkg:"))
async def choose_package(cb: CallbackQuery, state: FSMContext):
    await cb.answer()

    code = cb.data.split(":", 1)[1]
    package = get_package(code)
    if not package:
        await cb.message.answer("This V-Coin package is not available anymore.")
        return

    await state.set_state(VCoinBuyState.receipt)
    await state.update_data(package=package)

    await cb.message.answer(
        build_payment_details_text(package),
        parse_mode="HTML",
    )


@router.message(VCoinBuyState.receipt, F.photo | F.document)
async def receive_receipt(message: Message, state: FSMContext):
    data = await state.get_data()
    package = data.get("package")
    if not package:
        await state.clear()
        await message.answer("Please choose a V-Coin package again with /buy_vcoin.")
        return

    receipt = _receipt_from_message(message)
    if not receipt:
        await message.answer("Please send the receipt/check as a screenshot photo or document.")
        return

    if not backend_enabled():
        await message.answer(_backend_unavailable_text())
        return

    submitted_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "telegram_id": message.from_user.id,
        "username": message.from_user.username,
        "first_name": message.from_user.first_name,
        "full_name": message.from_user.full_name,
        "package_code": package["code"],
        "coins": package["coins"],
        "price": package["price"],
        "expected_amount": package["price"],
        "coins_to_add": package["coins"],
        "receipt_file_type": receipt["file_type"],
        "receipt_file_id": receipt["file_id"],
        "receipt_image_hash": receipt.get("file_unique_id"),
        "receipt_mime_type": receipt.get("mime_type"),
        "receipt_file_name": receipt.get("file_name"),
        "submitted_at": submitted_at,
        "source": "telegram_bot",
    }

    try:
        created = await create_payment_request(payload)
    except VCoinBackendError as exc:
        logger.warning("V-Coin receipt submission failed: %s", exc)
        await message.answer(_backend_unavailable_text())
        return

    payment_id = str(created.get("payment_id") or created.get("id") or "")
    status = created.get("status", "pending")
    backend_message = created.get("message", "")
    duplicate = bool(created.get("duplicate") or created.get("duplicate_suspected") or status == "duplicate_suspected")

    await state.clear()
    await message.answer(
        "Receipt received. We are checking your payment.\n\n"
        f"Status: {status}"
    )

    await _send_admin_receipt(
        message=message,
        payment_id=payment_id,
        package=package,
        receipt=receipt,
        status=status,
        submitted_at=submitted_at,
        backend_message=backend_message,
        duplicate=duplicate,
    )


@router.message(VCoinBuyState.receipt)
async def receipt_must_be_photo(message: Message):
    await message.answer("Please send the receipt/check as a screenshot photo or document.")


@router.message(F.photo | F.document)
async def receipt_without_package(message: Message):
    await message.answer("Please choose a V-Coin package first with /buy_vcoin.")


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
        await _mark_admin_message(
            cb,
            f"<b>Status:</b> confirmed signal sent for <code>{html.escape(payment_id)}</code>\n"
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
                await cb.bot.send_message(
                    chat_id=user_id,
                    text="Payment confirmed. Your V-Coins have been added.",
                )
            else:
                await cb.bot.send_message(
                    chat_id=user_id,
                    text="Payment could not be confirmed. Please contact admin or send a clearer receipt.",
                )
        except Exception:
            logger.exception("Failed to notify user %s about V-Coin %s", user_id, action)
