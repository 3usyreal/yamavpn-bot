import uuid

import aiohttp

import config

CRYPTO_API = "https://pay.crypt.bot/api"
YK_API = "https://api.yookassa.ru/v3"
TIMEOUT = aiohttp.ClientTimeout(total=20)


# ---------- Crypto Bot ----------
async def _crypto(method, http="GET", **params):
    headers = {"Crypto-Pay-API-Token": config.CRYPTO_PAY_TOKEN}
    kw = {"json": params} if http == "POST" else {"params": params}
    async with aiohttp.ClientSession(timeout=TIMEOUT) as s:
        async with s.request(http, f"{CRYPTO_API}/{method}", headers=headers, **kw) as r:
            data = await r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Crypto Pay error: {data}")
    return data["result"]


async def crypto_create(price_rub, description, payload):
    # Счёт выставляется в рублях, Crypto Bot сам пересчитывает в выбранную монету
    return await _crypto(
        "createInvoice", "POST",
        currency_type="fiat", fiat="RUB", amount=str(price_rub),
        description=description, payload=payload, expires_in=3600,
    )


async def crypto_paid(invoice_id):
    res = await _crypto("getInvoices", invoice_ids=str(invoice_id))
    items = res["items"] if isinstance(res, dict) else res
    return bool(items) and items[0].get("status") == "paid"


# ---------- ЮKassa ----------
def _yk_auth():
    return aiohttp.BasicAuth(config.YOOKASSA_SHOP_ID, config.YOOKASSA_SECRET_KEY)


async def yookassa_create(price_rub, description, metadata):
    body = {
        "amount": {"value": f"{int(price_rub)}.00", "currency": "RUB"},
        "capture": True,
        "confirmation": {"type": "redirect", "return_url": config.YOOKASSA_RETURN_URL},
        "description": description,
        "metadata": metadata,
    }
    async with aiohttp.ClientSession(timeout=TIMEOUT) as s:
        async with s.post(f"{YK_API}/payments", json=body, auth=_yk_auth(),
                          headers={"Idempotence-Key": str(uuid.uuid4())}) as r:
            data = await r.json()
            if r.status >= 400:
                raise RuntimeError(f"YooKassa error: {data}")
            return data


async def yookassa_paid(payment_id):
    async with aiohttp.ClientSession(timeout=TIMEOUT) as s:
        async with s.get(f"{YK_API}/payments/{payment_id}", auth=_yk_auth()) as r:
            data = await r.json()
            if r.status >= 400:
                raise RuntimeError(f"YooKassa error: {data}")
            return data.get("status") == "succeeded"


# ---------- общее ----------
async def is_paid(provider, ext_id):
    if provider == "crypto":
        return await crypto_paid(ext_id)
    if provider == "yookassa":
        return await yookassa_paid(ext_id)
    return False
