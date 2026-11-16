import os
import time

import aiosqlite

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    tg_id INTEGER PRIMARY KEY, ref_by INTEGER, created INTEGER, paid INTEGER DEFAULT 0, trial INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS payments(
    id INTEGER PRIMARY KEY AUTOINCREMENT, tg_id INTEGER, plan TEXT, provider TEXT,
    ext_id TEXT UNIQUE, status TEXT, created INTEGER);
"""


async def init():
    os.makedirs(os.path.dirname(config.DB_PATH) or ".", exist_ok=True)
    async with aiosqlite.connect(config.DB_PATH) as d:
        await d.executescript(SCHEMA)
        cur = await d.execute("PRAGMA table_info(users)")
        cols = [r[1] for r in await cur.fetchall()]
        if "trial" not in cols:  # миграция для уже созданной базы
            await d.execute("ALTER TABLE users ADD COLUMN trial INTEGER DEFAULT 0")
        await d.commit()


async def _exec(sql, args=()):
    async with aiosqlite.connect(config.DB_PATH) as d:
        cur = await d.execute(sql, args)
        await d.commit()
        return cur.rowcount


async def _one(sql, args=()):
    async with aiosqlite.connect(config.DB_PATH) as d:
        cur = await d.execute(sql, args)
        return await cur.fetchone()


async def _all(sql, args=()):
    async with aiosqlite.connect(config.DB_PATH) as d:
        cur = await d.execute(sql, args)
        return await cur.fetchall()


async def add_user(tg_id, ref):
    if ref == tg_id:
        ref = None
    await _exec("INSERT OR IGNORE INTO users(tg_id, ref_by, created) VALUES(?,?,?)",
                (tg_id, ref, int(time.time())))


async def add_payment(tg_id, plan, provider, ext_id, status):
    n = await _exec(
        "INSERT OR IGNORE INTO payments(tg_id, plan, provider, ext_id, status, created) VALUES(?,?,?,?,?,?)",
        (tg_id, plan, provider, ext_id, status, int(time.time())))
    return n == 1


async def pending():
    rows = await _all(
        "SELECT ext_id, provider FROM payments WHERE status='pending' AND created>?",
        (int(time.time()) - 86400,))
    return [(r[0], r[1]) for r in rows]


async def get_payment(ext_id):
    """Вернёт (tg_id, provider) или None."""
    return await _one("SELECT tg_id, provider FROM payments WHERE ext_id=?", (ext_id,))


async def claim_pending(ext_id):
    """Атомарно помечает платёж оплаченным. Вернёт (tg_id, plan) только один раз."""
    async with aiosqlite.connect(config.DB_PATH) as d:
        cur = await d.execute(
            "UPDATE payments SET status='paid' WHERE ext_id=? AND status='pending'",
            (ext_id,))
        await d.commit()
        if cur.rowcount != 1:
            return None
        cur = await d.execute("SELECT tg_id, plan FROM payments WHERE ext_id=?", (ext_id,))
        return await cur.fetchone()


async def first_paid(tg_id):
    """Если это первая оплата пользователя, вернёт id пригласившего (или None)."""
    n = await _exec("UPDATE users SET paid=1 WHERE tg_id=? AND paid=0", (tg_id,))
    if n != 1:
        return None
    row = await _one("SELECT ref_by FROM users WHERE tg_id=?", (tg_id,))
    return row[0] if row else None


async def count_refs(tg_id):
    return (await _one("SELECT COUNT(*) FROM users WHERE ref_by=?", (tg_id,)))[0]


async def stats():
    users = (await _one("SELECT COUNT(*) FROM users"))[0]
    paid = (await _one("SELECT COUNT(*) FROM users WHERE paid=1"))[0]
    return users, paid


async def trial_available(tg_id):
    row = await _one("SELECT trial, paid FROM users WHERE tg_id=?", (tg_id,))
    return bool(row) and row[0] == 0 and row[1] == 0


async def claim_trial(tg_id):
    """Атомарно отмечает пробный период использованным (один раз на пользователя)."""
    return await _exec("UPDATE users SET trial=1 WHERE tg_id=? AND trial=0 AND paid=0", (tg_id,)) == 1


async def release_trial(tg_id):
    await _exec("UPDATE users SET trial=0 WHERE tg_id=?", (tg_id,))
