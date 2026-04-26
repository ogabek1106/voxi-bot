import json
import os


FULL_MOCK_COST = 10
SEPARATE_BLOCK_COST = 3

BACKEND_URL = os.getenv("VCOIN_BACKEND_URL", "").rstrip("/")
BACKEND_TOKEN = os.getenv("VCOIN_BACKEND_TOKEN", "")

PAYMENT_CARD_TEXT = os.getenv(
    "VCOIN_PAYMENT_CARD_TEXT",
    """💳 PAYMENT DETAILS

Humo: `9860 1678 4915 6408`
Visa (USD): `4231 2000 1025 4109`

👤 Name: OGABEK RAYIMOV
🏦 Bank: Hamkor Bank

━━━━━━━━━━━━━━━

📸 After payment:
Send your receipt screenshot here

⏱️ You will be credited within a few minutes""",
)

DEFAULT_PACKAGES = [
    {"code": "p10", "coins": 10, "price": "50,000 so'm ($4)", "label": "1 Full Mock"},
    {"code": "p20", "coins": 20, "price": "90,000 so'm ($7)", "label": "2 Full Mocks ⭐ MOST POPULAR"},
    {"code": "p30", "coins": 30, "price": "120,000 so'm ($10)", "label": "3 Full Mocks 🔥 BEST VALUE"},
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

def build_vcoin_packages_text():
    packages = get_packages()

    lines = [
        "🎯 Practice IELTS in REAL exam conditions",
        "",
        f"Full Mock = {FULL_MOCK_COST} V-Coins",
        f"Single block = {SEPARATE_BLOCK_COST} V-Coins",
        "",
        "━━━━━━━━━━━━━━━",
        "",
        "💰 Choose your package:",
        "",
    ]

    for package in packages:
        coins = package["coins"]
        price = package["price"]
        label = package.get("label", "")

        lines.append(f"{coins} V-Coins — {price}")
        if label:
            lines.append(f"→ {label}")
        lines.append("")

    lines.extend([
        "━━━━━━━━━━━━━━━",
        "",
        PAYMENT_CARD_TEXT,
    ])

    return "\n".join(lines)
