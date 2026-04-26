import json
import os


FULL_MOCK_COST = 10
SEPARATE_BLOCK_COST = 3

BACKEND_URL = os.getenv("VCOIN_BACKEND_URL", "").rstrip("/")
BACKEND_TOKEN = os.getenv("VCOIN_BACKEND_TOKEN", "")

PAYMENT_CARD_TEXT = os.getenv(
    "VCOIN_PAYMENT_CARD_TEXT",
    """💳 Payment details

UzCard/Humo: 9860 1678 4915 6408
Visa: 4231 2000 1025 4109
Name: OGABEK RAYIMOV
Bank: Hamkor Bank

After payment, send the receipt screenshot here.""",
)


DEFAULT_PACKAGES = [
    {"code": "p10", "coins": 10, "price": "50 000 sums | $4"},
    {"code": "p30", "coins": 30, "price": "90 000 sums | $7"},
    {"code": "p50", "coins": 50, "price": "120 000 sums | $10"},
]


def get_packages():
    raw = os.getenv("VCOIN_PACKAGES_JSON")
    if not raw:
        return DEFAULT_PACKAGES

    try:
        packages = json.loads(raw)
    except json.JSONDecodeError:
        return DEFAULT_PACKAGES

    clean = []
    for item in packages if isinstance(packages, list) else []:
        code = str(item.get("code", "")).strip()
        coins = item.get("coins")
        price = str(item.get("price", "")).strip()
        if code and isinstance(coins, int) and coins > 0 and price:
            clean.append({"code": code, "coins": coins, "price": price})

    return clean or DEFAULT_PACKAGES


def get_package(code: str):
    for package in get_packages():
        if package["code"] == code:
            return package
    return None
