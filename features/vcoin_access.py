from typing import Tuple

from aiogram.types import Message

from features.vcoin_backend import VCoinBackendError, spend
from features.vcoin_config import FULL_MOCK_COST, SEPARATE_BLOCK_COST


FULL_MOCK_REASON = "full_mock_spending"
SEPARATE_BLOCK_REASON = "separate_block_spending"


async def charge_for_full_mock(message: Message, reference_id: str) -> Tuple[bool, str]:
    return await _charge(message, FULL_MOCK_COST, FULL_MOCK_REASON, reference_id)


async def charge_for_separate_block(message: Message, reference_id: str) -> Tuple[bool, str]:
    return await _charge(message, SEPARATE_BLOCK_COST, SEPARATE_BLOCK_REASON, reference_id)


async def _charge(message: Message, coins: int, reason: str, reference_id: str) -> Tuple[bool, str]:
    try:
        result = await spend(
            telegram_id=message.from_user.id,
            coins=coins,
            reason=reason,
            reference_id=reference_id,
        )
    except VCoinBackendError as exc:
        await message.answer(f"Payment check failed: {exc}")
        return False, "backend_error"

    if result.get("ok") is False or result.get("error") == "insufficient_vcoins":
        await message.answer(f"Not enough V-Coins. This content needs {coins} V-Coins.")
        return False, "insufficient_vcoins"

    return True, "charged"
