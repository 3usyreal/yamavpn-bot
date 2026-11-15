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

    async def create_user(self, name, expire):
        body = {
            "username": name,
            "proxies": {"vless": {"flow": "xtls-rprx-vision"}},
            "expire": expire,
            "data_limit": 0,
            "status": "active",
        }
        if config.INBOUND_TAG:
            body["inbounds"] = {"vless": [config.INBOUND_TAG]}
        return await self._req("POST", "/api/user", json=body)

    async def set_expire(self, name, expire):
        return await self._req("PUT", f"/api/user/{name}", json={"expire": expire, "status": "active"})

    async def hosts(self):
        data = await self._req("GET", "/api/hosts") or {}
        return [h for group in data.values() for h in group]
