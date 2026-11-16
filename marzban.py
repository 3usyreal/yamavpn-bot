import aiohttp

import config

TIMEOUT = aiohttp.ClientTimeout(total=20)


class Marzban:
    def __init__(self):
        self.token = None

    async def _login(self, s):
        async with s.post(
            f"{config.MARZBAN_URL}/api/admin/token",
            data={"username": config.MARZBAN_USER, "password": config.MARZBAN_PASS},
        ) as r:
            r.raise_for_status()
            self.token = (await r.json())["access_token"]

    async def _req(self, method, path, **kw):
        async with aiohttp.ClientSession(timeout=TIMEOUT) as s:
            for attempt in (1, 2):
                if not self.token:
                    await self._login(s)
                headers = {"Authorization": f"Bearer {self.token}"}
                async with s.request(method, config.MARZBAN_URL + path, headers=headers, **kw) as r:
                    if r.status == 401 and attempt == 1:
                        self.token = None
                        continue
                    if r.status == 404:
                        return None
                    r.raise_for_status()
                    return await r.json()

    async def get_user(self, name):
        return await self._req("GET", f"/api/user/{name}")

    async def vless_tags(self):
        """Теги всех VLESS-inbound из панели."""
        data = await self._req("GET", "/api/inbounds") or {}
        return [i["tag"] for i in data.get("vless", [])]

    async def create_user(self, name, expire):
        tags = [config.INBOUND_TAG] if config.INBOUND_TAG else await self.vless_tags()
        body = {
            "username": name,
            "proxies": {"vless": {"flow": config.VLESS_FLOW}},
            "expire": expire,
            "data_limit": 0,
            "status": "active",
        }
        if tags:
            body["inbounds"] = {"vless": tags}  # явно отмечаем VLESS Reality для пользователя
        u = await self._req("POST", "/api/user", json=body)
        await self.ensure_user(u)  # на случай, если панель не применила flow или inbound
        return u

    async def set_expire(self, name, expire):
        return await self._req("PUT", f"/api/user/{name}", json={"expire": expire, "status": "active"})

    async def hosts(self):
        data = await self._req("GET", "/api/hosts") or {}
        return [h for group in data.values() for h in group]

    async def ensure_flow(self, u):
        """Выставляет flow, если его нет. UUID пользователя сохраняется. Вернёт True, если правили."""
        vless = (u.get("proxies") or {}).get("vless")
        if vless is None or vless.get("flow") == config.VLESS_FLOW:
            return False
        await self._req("PUT", f"/api/user/{u['username']}",
                        json={"proxies": {"vless": {**vless, "flow": config.VLESS_FLOW}}})
        return True

    async def ensure_inbound(self, u):
        """Если у пользователя не отмечен ни один VLESS inbound, отмечает все. Вернёт True, если правили."""
        if (u.get("inbounds") or {}).get("vless"):
            return False
        tags = [config.INBOUND_TAG] if config.INBOUND_TAG else await self.vless_tags()
        if not tags:
            return False
        await self._req("PUT", f"/api/user/{u['username']}", json={"inbounds": {"vless": tags}})
        return True

    async def ensure_user(self, u):
        """flow + inbound. Вернёт True, если что-то исправили."""
        a = await self.ensure_flow(u)
        b = await self.ensure_inbound(u)
        return a or b

    async def list_users(self):
        users, offset = [], 0
        while True:
            data = await self._req("GET", f"/api/users?offset={offset}&limit=100") or {}
            batch = data.get("users", [])
            users += batch
            if len(batch) < 100:
                return users
            offset += 100
