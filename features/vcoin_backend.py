import logging
from typing import Any, Dict, Optional

import aiohttp

from features.vcoin_config import BACKEND_TOKEN, BACKEND_URL


logger = logging.getLogger(__name__)


class VCoinBackendError(Exception):
    pass


def backend_enabled() -> bool:
    return bool(BACKEND_URL)


async def _request(method: str, path: str, payload: Optional[Dict[str, Any]] = None):
    if not BACKEND_URL:
        raise VCoinBackendError("V-Coin backend is not configured.")

    headers = {"Content-Type": "application/json"}
    if BACKEND_TOKEN:
        headers["Authorization"] = f"Bearer {BACKEND_TOKEN}"

    url = f"{BACKEND_URL}{path}"
    timeout = aiohttp.ClientTimeout(total=20)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.request(method, url, json=payload, headers=headers) as resp:
            try:
                data = await resp.json()
            except Exception:
                data = {"text": await resp.text()}

            if resp.status >= 400:
                logger.warning("V-Coin backend error %s %s: %s", resp.status, path, data)
                raise VCoinBackendError(str(data))

            return data


async def get_balance(telegram_id: int):
    return await _request("GET", f"/vcoins/balance/{telegram_id}")


async def create_payment_request(payload: Dict[str, Any]):
    return await _request("POST", "/vcoins/payment-requests", payload)


async def confirm_payment(payment_id: str, admin_telegram_id: int):
    return await _request(
        "POST",
        f"/vcoins/payment-requests/{payment_id}/confirm",
        {"admin_telegram_id": admin_telegram_id},
    )


async def reject_payment(payment_id: str, admin_telegram_id: int, reason: str = ""):
    return await _request(
        "POST",
        f"/vcoins/payment-requests/{payment_id}/reject",
        {"admin_telegram_id": admin_telegram_id, "reason": reason},
    )


async def spend(telegram_id: int, coins: int, reason: str, reference_id: str):
    return await _request(
        "POST",
        "/vcoins/spend",
        {
            "telegram_id": telegram_id,
            "coins": coins,
            "reason": reason,
            "reference_id": reference_id,
        },
    )
