import html
import logging

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
    PAYMENT_CARD_TEXT,
    SEPARATE_BLOCK_COST,
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
        rows.append([
            InlineKeyboardButton(
                text=f'{package["coins"]} V-Coin - {package["price"]}',
                callback_data=f'vcoin_pkg:{package["code"]}',
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _admin_keyboard(payment_id: str):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Confirm", callback_data=f"vcoin_confirm:{payment_id}"),
        InlineKeyboardButton(text="Reject", callback_data=f"vcoin_reject:{payment_id}"),
    ]])


@router.message(Command("vcoins"))
async def vcoin_balance(message: Message):
    if not backend_enabled():
        await message.answer("V-Coin backend is not configured yet.")
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
@router.message(F.text.in_({"Buy V-Coin", "V-Coin", "Buy VCoin"}))
async def buy_vcoin(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Choose a V-Coin package:\n\n"
        f"Full Mock costs {FULL_MOCK_COST} V-Coins.\n"
        f"One separate block costs {SEPARATE_BLOCK_COST} V-Coins.",
        reply_markup=_packages_keyboard(),
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
        "Payment details\n\n"
        f'Package: {package["coins"]} V-Coin\n'
        f'Price: {package["price"]}\n\n'
        f"{PAYMENT_CARD_TEXT}\n\n"
        "After payment, send the receipt/check screenshot here."
    )


@router.message(VCoinBuyState.receipt, F.photo)
async def receive_receipt(message: Message, state: FSMContext):
    data = await state.get_data()
    package = data.get("package")
    if not package:
        await state.clear()
        await message.answer("Please choose a V-Coin package again with /buy_vcoin.")
        return

    if not backend_enabled():
        await message.answer("V-Coin backend is not configured yet. Receipt was not submitted.")
        return

    photo = message.photo[-1]
    payload = {
        "telegram_id": message.from_user.id,
        "username": message.from_user.username,
        "first_name": message.from_user.first_name,
        "expected_amount": package["price"],
        "coins_to_add": package["coins"],
        "receipt_file_id": photo.file_id,
        "receipt_image_hash": photo.file_unique_id,
        "source": "telegram_bot",
    }

    try:
        created = await create_payment_request(payload)
    except VCoinBackendError as exc:
        await message.answer(f"Receipt could not be submitted: {exc}")
        return

    payment_id = str(created.get("payment_id") or created.get("id") or "")
    status = created.get("status", "pending")

    await state.clear()
    await message.answer(
        "Receipt submitted.\n\n"
        f"Status: {status}\n"
        "Admin will review it and you will be notified after confirmation."
    )

    admin_text = (
        "V-Coin payment request\n\n"
        f"Payment ID: {html.escape(payment_id or 'unknown')}\n"
        f"User: {message.from_user.id}\n"
        f"Username: @{html.escape(message.from_user.username or '-')}\n"
        f'Package: {package["coins"]} V-Coin\n'
        f'Expected amount: {html.escape(str(package["price"]))}\n'
        f"Backend status: {html.escape(str(status))}"
    )

    for admin_id in ADMIN_IDS:
        try:
            await message.bot.send_photo(
                chat_id=admin_id,
                photo=photo.file_id,
                caption=admin_text,
                reply_markup=_admin_keyboard(payment_id) if payment_id else None,
                parse_mode="HTML",
            )
        except Exception:
            logger.exception("Failed to notify admin %s about V-Coin payment", admin_id)


@router.message(VCoinBuyState.receipt)
async def receipt_must_be_photo(message: Message):
    await message.answer("Please send the receipt/check as a screenshot photo.")


@router.callback_query(F.data.startswith("vcoin_confirm:"))
async def admin_confirm_vcoin(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("Admins only.", show_alert=True)
        return

    payment_id = cb.data.split(":", 1)[1]
    try:
        result = await confirm_payment(payment_id, cb.from_user.id)
    except VCoinBackendError as exc:
        await cb.answer("Backend rejected confirm.", show_alert=True)
        await cb.message.answer(f"Confirm failed: {exc}")
        return

    await cb.answer("Confirmed.")
    await cb.message.answer(f"Payment {payment_id} confirm signal sent. Status: {result.get('status', 'unknown')}")

    user_id = result.get("telegram_id")
    coins = result.get("coins_added") or result.get("coins_to_add")
    if user_id:
        try:
            await cb.bot.send_message(
                chat_id=user_id,
                text=f"Your V-Coin payment was confirmed. Added: {coins or 'confirmed'} V-Coin.",
            )
        except Exception:
            logger.exception("Failed to notify user %s about V-Coin confirmation", user_id)


@router.callback_query(F.data.startswith("vcoin_reject:"))
async def admin_reject_vcoin(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("Admins only.", show_alert=True)
        return

    payment_id = cb.data.split(":", 1)[1]
    try:
        result = await reject_payment(payment_id, cb.from_user.id, reason="admin_rejected")
    except VCoinBackendError as exc:
        await cb.answer("Backend rejected reject.", show_alert=True)
        await cb.message.answer(f"Reject failed: {exc}")
        return

    await cb.answer("Rejected.")
    await cb.message.answer(f"Payment {payment_id} reject signal sent. Status: {result.get('status', 'unknown')}")

    user_id = result.get("telegram_id")
    if user_id:
        try:
            await cb.bot.send_message(
                chat_id=user_id,
                text="Your V-Coin payment was rejected. No V-Coins were added.",
            )
        except Exception:
            logger.exception("Failed to notify user %s about V-Coin rejection", user_id)
