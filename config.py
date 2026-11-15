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

YOOKASSA_SHOP_ID = env("YOOKASSA_SHOP_ID")
YOOKASSA_SECRET_KEY = env("YOOKASSA_SECRET_KEY")
YOOKASSA_RETURN_URL = env("YOOKASSA_RETURN_URL", "https://t.me/YamaVPNGateBot")

# Тарифы. Цены в рублях (целые числа). Поменяйте под себя.
PLANS = {
    "m1": {"title": "1 месяц", "days": 30, "price": 199},
    "m3": {"title": "3 месяца", "days": 90, "price": 549},
    "m12": {"title": "12 месяцев", "days": 365, "price": 1990},
}
