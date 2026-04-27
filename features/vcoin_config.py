import html
import json
import os
import re


FULL_MOCK_COST = 10
SEPARATE_BLOCK_COST = 3

BACKEND_URL = os.getenv(
    "VCOIN_BACKEND_URL",
    "https://voxi-miniapp-production.up.railway.app",
).rstrip("/")
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
        label = str(item.get("label", "")).strip()
        if code and isinstance(coins, int) and coins > 0 and price:
            package = {"code": code, "coins": coins, "price": price}
            if label:
                package["label"] = label
            clean.append(package)

    return clean or DEFAULT_PACKAGES


def get_package(code: str):
    for package in get_packages():
        if package["code"] == code:
            return package
    return None


def _html(text) -> str:
    return html.escape(str(text), quote=False)


def _format_card_numbers(text: str) -> str:
    escaped = _html(text)

    def repl(match):
        value = match.group(0)
        digits = re.sub(r"\D", "", value)
        if 12 <= len(digits) <= 19:
            return f"<code>{value}</code>"
        return value

    return re.sub(r"(?<!\d)(?:\d[ -]?){12,19}(?!\d)", repl, escaped)


def build_payment_details_text(package):
    coins = _html(package["coins"])
    price = _html(package["price"])

    return "\n".join([
        "<b>💳 Payment details</b>",
        "",
        f"<b>Package:</b> {coins} V-Coin",
        f"<b>Price:</b> <i>{price}</i>",
        "",
        _format_card_numbers(PAYMENT_CARD_TEXT),
        "",
        "<i>After payment, send the receipt/check screenshot here.</i>",
    ])


def build_vcoin_packages_text():
    packages = get_packages()

    lines = [
        "<b>🎯 Practice IELTS in REAL exam conditions</b>",
        "",
        f"<b>Full Mock</b> = <code>{FULL_MOCK_COST}</code> V-Coins",
        f"<b>Single block</b> = <code>{SEPARATE_BLOCK_COST}</code> V-Coins",
        "",
        "━━━━━━━━━━━━━━━",
        "",
        "<b>💰 Choose your package:</b>",
        "",
    ]

    for package in packages:
        coins = _html(package["coins"])
        price = _html(package["price"])
        label = _html(package.get("label", ""))

        lines.append(f"<b>{coins} V-Coins</b> — <i>{price}</i>")
        if label:
            lines.append(f"→ <i>{label}</i>")
        lines.append("")

    lines.extend([
        "━━━━━━━━━━━━━━━",
        "",
        _format_card_numbers(PAYMENT_CARD_TEXT),
    ])

    return "\n".join(lines)
