import asyncio
import html
import logging
import re
import time

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, ErrorEvent, LabeledPrice, Message, PreCheckoutQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
import db
import payments
from marzban import Marzban

log = logging.getLogger("bot")
router = Router()
mz = Marzban()

HELP_TEXT = (
    "<b>Как подключиться</b>\n\n"
    "1. Установите приложение:\n"
    "• iPhone: Streisand или Happ\n"
    "• Android: v2rayNG или Hiddify\n"
    "• Windows / macOS: Hiddify\n\n"
    "2. В боте откройте «Мои подписки» и скопируйте ссылку подписки.\n"
    "3. В приложении добавьте подписку по URL (из буфера обмена) и включите VPN.\n\n"
    "Если что-то не работает, напишите в поддержку."
)


# ---------- вспомогательное ----------
def uname(tg_id: int) -> str:
    return f"tg{tg_id}"


def fmt_date(ts) -> str:
    return time.strftime("%d.%m.%Y %H:%M", time.localtime(ts)) if ts else "бессрочно"


def kb(rows):
    b = InlineKeyboardBuilder()
    for text, target in rows:
        if not target:
            continue
        if target.startswith("http"):
            b.button(text=text, url=target)
        else:
            b.button(text=text, callback_data=target)
    b.adjust(1)
    return b.as_markup()


HOME = ("🏠 Главное меню", "menu")


def main_menu():
    return kb([
        ("📁 Мои подписки", "subs"),
        ("💳 Оплата", "pay"),
        ("⚡ Бонусы", "bonus"),
        ("🌐 Список серверов", "servers"),
        ("💡 Инструкции и поддержка", "help"),
        ("📣 Наш канал", config.CHANNEL_URL),
        ("💬 Наш чат", config.CHAT_URL),
    ])


async def show(c: CallbackQuery, text: str, markup=None):
    try:
        await c.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as e:
        if "not modified" not in str(e):
            await c.message.answer(text, reply_markup=markup)
    await c.answer()


async def menu_text(tg_id: int) -> str:
    u = await mz.get_user(uname(tg_id))
    if not u:
        line = "Подписки пока нет."
    else:
        icon = "✅" if u["status"] == "active" else "⛔️"
        line = f"{icon} Подписка 1 — до {fmt_date(u.get('expire'))}"
    return f"<b>Привет!</b>\nВаш ID: <code>{tg_id}</code>\n\n{line}"


# ---------- выдача подписки ----------
async def grant(tg_id: int, days: int):
    name, now = uname(tg_id), int(time.time())
    u = await mz.get_user(name)
    if u:
        base = max(now, u.get("expire") or 0)
        await mz.set_expire(name, base + days * 86400)
    else:
        await mz.create_user(name, now + days * 86400)


async def fulfill(bot: Bot, tg_id: int, plan: str):
    await grant(tg_id, config.PLANS[plan]["days"])
    u = await mz.get_user(uname(tg_id))
    await bot.send_message(
        tg_id,
        f"✅ Оплата получена!\nПодписка активна до {fmt_date(u.get('expire'))}\n\n"
        f"Ссылка подписки:\n<code>{u['subscription_url']}</code>",
        reply_markup=kb([("📁 Мои подписки", "subs"), ("💡 Инструкции", "help")]),
    )
    ref = await db.first_paid(tg_id)
    if ref:
        try:
            await grant(ref, config.REF_BONUS_DAYS)
            await bot.send_message(ref, f"🎁 Ваш друг оформил подписку. Вам начислено +{config.REF_BONUS_DAYS} дн.")
        except Exception:
            log.exception("referral bonus failed")


async def settle_crypto(bot: Bot, invoice_id):
    row = await db.claim_pending(str(invoice_id))
    if row:
        await fulfill(bot, row[0], row[1])
    return bool(row)


# ---------- команды ----------
@router.message(CommandStart())
async def start(m: Message, command: CommandObject):
    ref = None
    if command.args and command.args.startswith("ref_") and command.args[4:].isdigit():
        ref = int(command.args[4:])
    await db.add_user(m.from_user.id, ref)
    await m.answer(await menu_text(m.from_user.id), reply_markup=main_menu())


@router.message(Command("grant"))
async def cmd_grant(m: Message, command: CommandObject):
    if m.from_user.id not in config.ADMIN_IDS:
        return
    try:
        tg_id, days = map(int, command.args.split())
    except Exception:
        return await m.answer("Формат: /grant tg_id дней")
    await grant(tg_id, days)
    await m.answer("Готово.")


@router.message(Command("stats"))
async def cmd_stats(m: Message):
    if m.from_user.id not in config.ADMIN_IDS:
        return
    users, paid = await db.stats()
    await m.answer(f"Пользователей: {users}\nОплативших: {paid}")


# ---------- меню ----------
@router.callback_query(F.data == "menu")
async def cb_menu(c: CallbackQuery):
    await show(c, await menu_text(c.from_user.id), main_menu())


@router.callback_query(F.data == "subs")
async def cb_subs(c: CallbackQuery):
    u = await mz.get_user(uname(c.from_user.id))
    if not u:
        return await show(c, "У вас пока нет подписок.", kb([("💳 Оплата", "pay"), HOME]))
    icon = "✅" if u["status"] == "active" else "⛔️"
    await show(c, "<b>Мои подписки</b>\n\nВыберите подписку для управления:",
               kb([(f"{icon} Подписка 1", "sub1"), HOME]))


@router.callback_query(F.data == "sub1")
async def cb_sub1(c: CallbackQuery):
    u = await mz.get_user(uname(c.from_user.id))
    if not u:
        return await show(c, "Подписка не найдена.", kb([("💳 Оплата", "pay"), HOME]))
    status = "активна" if u["status"] == "active" else "неактивна"
    used = (u.get("used_traffic") or 0) / 1024 ** 3
    text = (
        f"<b>Подписка 1</b>\nСтатус: {status}\nДо: {fmt_date(u.get('expire'))}\n"
        f"Трафик: {used:.1f} ГБ / ∞\n\nСсылка подписки (нажмите, чтобы скопировать):\n"
        f"<code>{u['subscription_url']}</code>"
    )
    await show(c, text, kb([("🔄 Продлить", "pay"), ("💡 Инструкции", "help"), HOME]))


@router.callback_query(F.data == "help")
async def cb_help(c: CallbackQuery):
    await show(c, HELP_TEXT, kb([("🛟 Поддержка", config.SUPPORT_URL), HOME]))


@router.callback_query(F.data == "servers")
async def cb_servers(c: CallbackQuery):
    names = []
    for h in await mz.hosts():
        if h.get("is_disabled"):
            continue
        name = re.sub(r"\{[^}]*\}", "", h.get("remark", "")).strip()
        if name and name not in names:
            names.append(name)
    text = "<b>Список серверов</b>\n\n" + ("\n".join(f"• {html.escape(n)}" for n in names) or "Пока пусто.")
    await show(c, text, kb([HOME]))


@router.callback_query(F.data == "bonus")
async def cb_bonus(c: CallbackQuery):
    me = await c.bot.me()
    n = await db.count_refs(c.from_user.id)
    text = (
        "<b>Бонусы</b>\n\nПриглашайте друзей: когда друг впервые оплатит подписку, "
        f"вы получите +{config.REF_BONUS_DAYS} дней.\n\n"
        f"Ваша ссылка:\n<code>https://t.me/{me.username}?start=ref_{c.from_user.id}</code>\n\n"
        f"Приглашено: {n}"
    )
    await show(c, text, kb([HOME]))


# ---------- оплата ----------
@router.callback_query(F.data == "pay")
async def cb_pay(c: CallbackQuery):
    rows = [(f"{p['title']} — {p['stars']}⭐ / {p['usdt']} USDT", f"plan:{k}") for k, p in config.PLANS.items()]
    await show(c, "<b>Оплата</b>\n\nБезлимитный трафик. Выберите срок:", kb(rows + [HOME]))


@router.callback_query(F.data.startswith("plan:"))
async def cb_plan(c: CallbackQuery):
    key = c.data.split(":")[1]
    p = config.PLANS[key]
    rows = [("⭐ Telegram Stars", f"paystars:{key}")]
    if config.CRYPTO_PAY_TOKEN:
        rows.append(("🪙 Crypto Bot", f"paycrypto:{key}"))
    # Сюда позже добавим СБП и банковскую карту РФ
    await show(c, f"Тариф: <b>{p['title']}</b>\nВыберите способ оплаты:", kb(rows + [("⬅️ Назад", "pay")]))


@router.callback_query(F.data.startswith("paystars:"))
async def cb_stars(c: CallbackQuery):
    key = c.data.split(":")[1]
    p = config.PLANS[key]
    await c.message.answer_invoice(
        title=f"YamaVPN — {p['title']}",
        description="Доступ к VPN, безлимитный трафик",
        payload=f"plan:{key}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label=p["title"], amount=p["stars"])],
    )
    await c.answer()


@router.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery):
    await q.answer(ok=True)


@router.message(F.successful_payment)
async def on_paid(m: Message):
    sp = m.successful_payment
    key = sp.invoice_payload.split(":")[1]
    if await db.add_payment(m.from_user.id, key, "stars", sp.telegram_payment_charge_id, "paid"):
        await fulfill(m.bot, m.from_user.id, key)


@router.callback_query(F.data.startswith("paycrypto:"))
async def cb_crypto(c: CallbackQuery):
    key = c.data.split(":")[1]
    p = config.PLANS[key]
    inv = await payments.create_invoice(p["usdt"], f"YamaVPN — {p['title']}", f"{c.from_user.id}:{key}")
    await db.add_payment(c.from_user.id, key, "crypto", str(inv["invoice_id"]), "pending")
    url = inv.get("bot_invoice_url") or inv.get("pay_url")
    await show(
        c,
        f"Счёт на <b>{p['usdt']} USDT</b> создан. После оплаты подписка активируется автоматически (до минуты).",
        kb([("🪙 Оплатить в Crypto Bot", url), ("✅ Я оплатил", f"check:{inv['invoice_id']}"), HOME]),
    )


@router.callback_query(F.data.startswith("check:"))
async def cb_check(c: CallbackQuery):
    inv_id = c.data.split(":")[1]
    if await payments.is_paid(inv_id):
        await settle_crypto(c.bot, inv_id)
        await c.answer("Оплата получена!", show_alert=True)
    else:
        await c.answer("Оплата пока не найдена. Подождите минуту.", show_alert=True)


@router.error()
async def on_error(e: ErrorEvent):
    log.exception("handler error", exc_info=e.exception)
    upd = e.update
    if upd.callback_query:
        await upd.callback_query.answer("Ошибка сервиса, попробуйте позже", show_alert=True)
    elif upd.message:
        await upd.message.answer("Ошибка сервиса, попробуйте позже.")


# ---------- фон ----------
async def poll_crypto(bot: Bot):
    while True:
        try:
            for ext_id in await db.pending_crypto():
                if await payments.is_paid(ext_id):
                    await settle_crypto(bot, ext_id)
        except Exception:
            log.exception("crypto poll failed")
        await asyncio.sleep(20)


async def main():
    logging.basicConfig(level=logging.INFO)
    await db.init()
    bot = Bot(config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    if config.CRYPTO_PAY_TOKEN:
        task = asyncio.create_task(poll_crypto(bot))  # noqa: F841
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
