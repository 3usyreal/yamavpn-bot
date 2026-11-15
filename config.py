import os

from dotenv import load_dotenv

load_dotenv()


def env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


BOT_TOKEN = env("BOT_TOKEN")
ADMIN_IDS = {int(x) for x in env("ADMIN_IDS").split(",") if x.strip()}
CRYPTO_PAY_TOKEN = env("CRYPTO_PAY_TOKEN")

MARZBAN_URL = env("MARZBAN_URL", "https://yamavpn.duckdns.org:8000").rstrip("/")
MARZBAN_USER = env("MARZBAN_USER")
MARZBAN_PASS = env("MARZBAN_PASS")
INBOUND_TAG = env("INBOUND_TAG")

SUPPORT_URL = env("SUPPORT_URL")
CHANNEL_URL = env("CHANNEL_URL")
CHAT_URL = env("CHAT_URL")
REF_BONUS_DAYS = int(env("REF_BONUS_DAYS", "7"))
DB_PATH = env("DB_PATH", "/data/bot.db")

# Тарифы. ЦЕНЫ ЗДЕСЬ ПРИМЕРНЫЕ: поставьте свои.
# stars: цена в Telegram Stars, usdt: цена в USDT (строкой)
PLANS = {
    "m1": {"title": "1 месяц", "days": 30, "stars": 150, "usdt": "1.5"},
    "m3": {"title": "3 месяца", "days": 90, "stars": 400, "usdt": "4"},
    "m12": {"title": "12 месяцев", "days": 365, "stars": 1400, "usdt": "14"},
}
