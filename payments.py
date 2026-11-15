import aiohttp

import config

API = "https://pay.crypt.bot/api"


async def _call(method, http="GET", **params):
    headers = {"Crypto-Pay-API-Token": config.CRYPTO_PAY_TOKEN}
    kw = {"json": params} if http == "POST" else {"params": params}
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.request(http, f"{API}/{method}", headers=headers, **kw) as r:
            data = await r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Crypto Pay error: {data}")
    return data["result"]


async def create_invoice(amount, description, payload):
    return await _call(
        "createInvoice", "POST",
        asset="USDT", amount=str(amount), description=description,
        payload=payload, expires_in=3600,
    )


async def is_paid(invoice_id):
    res = await _call("getInvoices", invoice_ids=str(invoice_id))
    items = res["items"] if isinstance(res, dict) else res
    return bool(items) and items[0].get("status") == "paid"
