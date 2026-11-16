import asyncio
import html
import logging
import re
import time

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, CopyTextButton, ErrorEvent, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
import db
import payments
from marzban import Marzban

log = logging.getLogger("bot")
router = Router()
mz = Marzban()

HELP_TEXT = (
    "<b>💡 Как подключиться</b>\n\n"
    "<b>1️⃣ Установите приложение</b>\n"
    "⭐ Основное: <b>Karing</b>\n"
    "🔹 Запасное: <b>Incy</b>\n"
    "Оба бесплатные, есть для iPhone, Android, Windows и macOS. "
    "Найдите их по названию в App Store или Google Play. Если в вашем магазине приложения нет, "
    "скачайте его с сайта разработчика.\n\n"
    "<b>2️⃣ Скопируйте ссылку подписки</b>\n"
    "«Мои подписки» → «Подписка 1» → «Скопировать ссылку».\n\n"
    "<b>3️⃣ Добавьте её в приложение</b>\n"
    "Нажмите «+» (добавить профиль) и выберите импорт подписки по ссылке или из буфера обмена. "
    "При первом запуске на iPhone разрешите добавление VPN-конфигурации.\n\n"
    "<b>4️⃣ Включите соединение</b> и проверьте, что интернет работает.\n\n"
    "<b>Не подключается?</b>\n"
    "• Обновите подписку в приложении (кнопка обновления рядом с ней)\n"
    "• Попробуйте второе приложение (Incy, если был Karing, и наоборот)\n"
    "• Напишите в поддержку, мы поможем"
)


# ---------- вспомогательное ----------
def uname(tg_id: int) -> str:
    return f"tg{tg_id}"


def fmt_date(ts) -> str:
    return time.strftime("%d.%m.%Y %H:%M", time.localtime(ts)) if ts else "бессрочно"


def days_left(ts) -> str:
    if not ts:
        return "без ограничения срока"
    left = ts - time.time()
    if left <= 0:
        return "срок истёк"
    d = int(left // 86400)
    if d >= 1:
        return f"{d} дн."
    return f"{max(1, int(left // 3600))} ч."


def kb(rows):
    b = InlineKeyboardBuilder()
    for text, target in rows:
        if not target:
            continue
        if target.startswith("copy:"):
            b.button(text=text, copy_text=CopyTextButton(text=target[5:]))
        elif target.startswith("http"):
            b.button(text=text, url=target)
        else:
            b.button(text=text, callback_data=target)
    b.adjust(1)
    return b.as_markup()


HOME = ("🏠 Главное меню", "menu")


def copy_row(url: str):
    """Кнопка «скопировать» (лимит Telegram на текст кнопки: 256 символов)."""
    return [("📋 Скопировать ссылку", "copy:" + url)] if len(url) <= 256 else []


def main_menu(trial: bool = False):
    trial_row = [(f"🎁 Попробовать бесплатно ({config.TRIAL_DAYS} дн.)", "trial")] if trial else []
    return kb(trial_row + [
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
        price = config.PLANS["m1"]["price"]
        return (
            "👋 <b>Привет! Это YamaVPN</b>\n"
            "<i>Просто и надёжно</i>\n\n"
            f"🆔 Ваш ID: <code>{tg_id}</code>\n"
            "📭 Подписки пока нет\n\n"
            "<b>🚀 Как начать</b>\n"
            "1️⃣ Откройте «Оплата» и выберите тариф\n"
            "2️⃣ Получите ссылку подписки\n"
            "3️⃣ Вставьте её в приложение (шаги в «Инструкциях»)\n\n"
            f"💰 Тарифы от {price} ₽ в месяц · трафик без ограничений\n"
            f"🎁 Новым пользователям: {config.TRIAL_DAYS} дн. бесплатно"
        )
    active = u["status"] == "active" and (not u.get("expire") or u["expire"] > time.time())
    if active:
        return (
            "👋 <b>YamaVPN</b>\n"
            "<i>Просто и надёжно</i>\n\n"
            f"🆔 Ваш ID: <code>{tg_id}</code>\n"
            "✅ Подписка активна\n"
            f"📅 До: {fmt_date(u.get('expire'))}\n"
            f"⏳ Осталось: {days_left(u.get('expire'))}"
        )
    return (
        "👋 <b>YamaVPN</b>\n"
        "<i>Просто и надёжно</i>\n\n"
        f"🆔 Ваш ID: <code>{tg_id}</code>\n"
        "⛔️ Подписка закончилась\n"
        f"📅 Была до: {fmt_date(u.get('expire'))}\n\n"
        "Продлите её в разделе «Оплата», и ссылка заработает снова."
    )


async def trial_ok(tg_id: int) -> bool:
    return await db.trial_available(tg_id) and await mz.get_user(uname(tg_id)) is None


# ---------- выдача подписки ----------
async def grant(tg_id: int, days: int):
    name, now = uname(tg_id), int(time.time())
    u = await mz.get_user(name)
    if u:
        base = max(now, u.get("expire") or 0)
        await mz.ensure_user(u)
        await mz.set_expire(name, base + days * 86400)
    else:
        await mz.create_user(name, now + days * 86400)


async def fulfill(bot: Bot, tg_id: int, plan: str):
    await grant(tg_id, config.PLANS[plan]["days"])
    u = await mz.get_user(uname(tg_id))
    url = u["subscription_url"]
    await bot.send_message(
        tg_id,
        f"✅ <b>Оплата получена!</b>\nПодписка активна до {fmt_date(u.get('expire'))}\n\n"
        f"<b>Ваша ссылка подписки</b> (нажмите на неё или на кнопку ниже, чтобы скопировать):\n"
        f"<code>{url}</code>\n\n"
        "Вставьте её в приложение: подробнее в «Инструкциях».",
        reply_markup=kb(copy_row(url) + [("💡 Инструкции", "help"), ("📁 Мои подписки", "subs")]),
    )
    ref = await db.first_paid(tg_id)
    if ref:
        try:
            await grant(ref, config.REF_BONUS_DAYS)
            await bot.send_message(ref, f"🎁 Ваш друг оформил подписку. Вам начислено +{config.REF_BONUS_DAYS} дн.")
        except Exception:
            log.exception("referral bonus failed")


async def settle(bot: Bot, ext_id):
    row = await db.claim_pending(str(ext_id))
    if row:
        await fulfill(bot, row[0], row[1])
    return bool(row)


# ---------- обязательная подписка на канал ----------
async def is_subscribed(bot: Bot, user_id: int) -> bool:
    try:
        mem = await bot.get_chat_member(config.CHANNEL_ID, user_id)
    except Exception:
        log.exception("get_chat_member failed: бот не админ канала или неверный CHANNEL_ID?")
        return True  # не блокируем всех из-за сбоя
    return mem.status in ("member", "administrator", "creator") or (
        mem.status == "restricted" and mem.is_member)


class SubGate(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = event.from_user
        if not config.CHANNEL_ID or user.id in config.ADMIN_IDS:
            return await handler(event, data)
        if isinstance(event, CallbackQuery) and event.data == "chk_sub":
            return await handler(event, data)
        if await is_subscribed(event.bot, user.id):
            return await handler(event, data)
        # не теряем реферальную ссылку, пока человек подписывается
        if isinstance(event, Message) and event.text and event.text.startswith("/start ref_"):
            arg = event.text.split("ref_", 1)[1].strip()
            if arg.isdigit():
                await db.add_user(user.id, int(arg))
        text = "Чтобы пользоваться ботом, подпишитесь на наш канал, а затем нажмите «Проверить подписку»."
        markup = kb([("📣 Подписаться", config.CHANNEL_URL), ("✅ Проверить подписку", "chk_sub")])
        if isinstance(event, CallbackQuery):
            await event.message.answer(text, reply_markup=markup)
            await event.answer()
        else:
            await event.answer(text, reply_markup=markup)


router.message.outer_middleware(SubGate())
router.callback_query.outer_middleware(SubGate())


@router.callback_query(F.data == "chk_sub")
async def cb_chk_sub(c: CallbackQuery):
    if not await is_subscribed(c.bot, c.from_user.id):
        return await c.answer("Подписка не найдена. Подпишитесь на канал и повторите.", show_alert=True)
    await db.add_user(c.from_user.id, None)
    await c.message.answer(await menu_text(c.from_user.id),
                           reply_markup=main_menu(await trial_ok(c.from_user.id)))
    await c.answer()


# ---------- команды ----------
@router.message(CommandStart())
async def start(m: Message, command: CommandObject):
    ref = None
    if command.args and command.args.startswith("ref_") and command.args[4:].isdigit():
        ref = int(command.args[4:])
    await db.add_user(m.from_user.id, ref)
    await m.answer(await menu_text(m.from_user.id), reply_markup=main_menu(await trial_ok(m.from_user.id)))


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


@router.message(Command("fixflow"))
async def cmd_fixflow(m: Message):
    """Админ: выставить flow и отметить VLESS inbound у всех существующих пользователей (UUID не меняется)."""
    if m.from_user.id not in config.ADMIN_IDS:
        return
    n = 0
    for u in await mz.list_users():
        if await mz.ensure_user(u):
            n += 1
    await m.answer(f"Исправлено пользователей: {n}")


@router.message(Command("stats"))
async def cmd_stats(m: Message):
    if m.from_user.id not in config.ADMIN_IDS:
        return
    users, paid = await db.stats()
    await m.answer(f"Пользователей: {users}\nОплативших: {paid}")


# ---------- меню ----------
@router.callback_query(F.data == "menu")
async def cb_menu(c: CallbackQuery):
    await show(c, await menu_text(c.from_user.id), main_menu(await trial_ok(c.from_user.id)))


@router.callback_query(F.data == "trial")
async def cb_trial(c: CallbackQuery):
    tg_id = c.from_user.id
    if await mz.get_user(uname(tg_id)) is not None or not await db.claim_trial(tg_id):
        return await c.answer("Пробный период доступен один раз и уже использован.", show_alert=True)
    try:
        await grant(tg_id, config.TRIAL_DAYS)
        u = await mz.get_user(uname(tg_id))
    except Exception:
        await db.release_trial(tg_id)  # не сжигаем пробный период при сбое
        raise
    await show(
        c,
        f"🎁 Пробный период на {config.TRIAL_DAYS} дн. активирован!\nДо {fmt_date(u.get('expire'))}\n\n"
        f"Ссылка подписки (нажмите, чтобы скопировать):\n<code>{u['subscription_url']}</code>",
        kb(copy_row(u["subscription_url"]) + [("💡 Инструкции", "help"), ("💳 Оплата", "pay"), HOME]),
    )


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
    await show(c, text, kb(copy_row(u["subscription_url"]) + [("🔄 Продлить", "pay"), ("💡 Инструкции", "help"), HOME]))


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
    rows = [(f"{p['title']} — {p['price']} ₽", f"plan:{k}") for k, p in config.PLANS.items()]
    await show(c, "<b>Оплата</b>\n\nБезлимитный трафик. Выберите срок:", kb(rows + [HOME]))


@router.callback_query(F.data.startswith("plan:"))
async def cb_plan(c: CallbackQuery):
    key = c.data.split(":")[1]
    p = config.PLANS[key]
    rows = []
    if config.YOOKASSA_SHOP_ID and config.YOOKASSA_SECRET_KEY:
        rows.append(("💳 Карта / СБП", f"payyoo:{key}"))
    if config.CRYPTO_PAY_TOKEN:
        rows.append(("🪙 Crypto Bot", f"paycrypto:{key}"))
    if not rows:
        return await show(c, "Оплата временно недоступна. Напишите в поддержку.",
                          kb([("🛟 Поддержка", config.SUPPORT_URL), HOME]))
    await show(c, f"Тариф: <b>{p['title']}</b> — {p['price']} ₽\nВыберите способ оплаты:",
               kb(rows + [("⬅️ Назад", "pay")]))


@router.callback_query(F.data.startswith("payyoo:"))
async def cb_yoo(c: CallbackQuery):
    key = c.data.split(":")[1]
    p = config.PLANS[key]
    pay = await payments.yookassa_create(
        p["price"], f"YamaVPN — {p['title']}", {"tg_id": str(c.from_user.id), "plan": key})
    await db.add_payment(c.from_user.id, key, "yookassa", pay["id"], "pending")
    url = pay["confirmation"]["confirmation_url"]
    await show(
        c,
        f"Счёт на <b>{p['price']} ₽</b> создан. После оплаты подписка активируется автоматически (до минуты).",
        kb([("💳 Оплатить", url), ("✅ Я оплатил", f"check:{pay['id']}"), HOME]),
    )


@router.callback_query(F.data.startswith("paycrypto:"))
async def cb_crypto(c: CallbackQuery):
    key = c.data.split(":")[1]
    p = config.PLANS[key]
    inv = await payments.crypto_create(p["price"], f"YamaVPN — {p['title']}", f"{c.from_user.id}:{key}")
    await db.add_payment(c.from_user.id, key, "crypto", str(inv["invoice_id"]), "pending")
    url = inv.get("bot_invoice_url") or inv.get("pay_url")
    await show(
        c,
        f"Счёт на <b>{p['price']} ₽</b> (в криптовалюте по курсу) создан. "
        "После оплаты подписка активируется автоматически (до минуты).",
        kb([("🪙 Оплатить в Crypto Bot", url), ("✅ Я оплатил", f"check:{inv['invoice_id']}"), HOME]),
    )


@router.callback_query(F.data.startswith("check:"))
async def cb_check(c: CallbackQuery):
    ext_id = c.data.split(":")[1]
    row = await db.get_payment(ext_id)
    if not row or row[0] != c.from_user.id:
        return await c.answer("Платёж не найден.", show_alert=True)
    if await payments.is_paid(row[1], ext_id):
        await settle(c.bot, ext_id)
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
async def poll_payments(bot: Bot):
    while True:
        try:
            items = await db.pending()
        except Exception:
            log.exception("db pending failed")
            items = []
        for ext_id, provider in items:
            try:
                if await payments.is_paid(provider, ext_id):
                    await settle(bot, ext_id)
            except Exception:
                log.exception("payment check failed: %s", ext_id)
        await asyncio.sleep(20)


async def main():
    logging.basicConfig(level=logging.INFO)
    await db.init()
    bot = Bot(config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    task = asyncio.create_task(poll_payments(bot))  # noqa: F841
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
