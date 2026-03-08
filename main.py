"""
Convert Bot v7.0 — с выбором валюты и автоудалением
  pip install pytelegrambotapi requests
  python bot.py
"""

import hashlib
import logging
import threading
import time
from collections import defaultdict
from datetime import datetime

import requests
import telebot
from telebot import types

# ─────────────────────────────────────────
#  НАСТРОЙКИ
# ─────────────────────────────────────────
BOT_TOKEN = "8688848833:AAEIJ6w7BfCuwH9gdc0mpLW_vNdOXtiTIas"  # токен от @BotFather
ADMIN_IDS = {6708567261}  # ваш Telegram ID (@userinfobot)
RATE_UPDATE_SEC = 60  # обновление курсов каждую минуту (для точности)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s"
)
log = logging.getLogger(__name__)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)

# ─────────────────────────────────────────
#  МОНЕТЫ
# ─────────────────────────────────────────
COINS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "TON": "the-open-network",
    "BNB": "binancecoin",
    "SOL": "solana",
    "USDT": "tether",
    "USDC": "usd-coin",
    "XRP": "ripple",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "TRX": "tron",
    "DOT": "polkadot",
    "MATIC": "matic-network",
    "LTC": "litecoin",
    "AVAX": "avalanche-2",
    "SHIB": "shiba-inu",
    "LINK": "chainlink",
    "UNI": "uniswap",
    "ATOM": "cosmos",
    "XLM": "stellar",
    "USD": None,
    "EUR": None,
    "RUB": None,
}
FIAT = {"USD", "EUR", "RUB"}

# ─────────────────────────────────────────
#  ДАННЫЕ ПОЛЬЗОВАТЕЛЕЙ
# ─────────────────────────────────────────
user_lang: dict = {}  # uid -> "ru"/"en"/"ua"
user_currency: dict = {}  # uid -> "USD"/"RUB" (валюта отображения)
user_history: dict = defaultdict(list)  # uid -> [{frm,to,amount,result,ts}, ...]
user_stats: dict = defaultdict(lambda: {"cnt": 0, "last": "—", "name": ""})
user_favorites: dict = defaultdict(list)  # uid -> [("BTC","USD"), ...]
user_portfolio: dict = defaultdict(dict)  # uid -> {"BTC": 0.5, ...}
user_alerts: dict = defaultdict(list)  # uid -> [{coin,op,price,active}, ...]
user_state: dict = {}  # uid -> состояние FSM
user_last_msg: dict = {}  # uid -> id последнего сообщения для удаления
all_users: set = set()
bot_start_time = datetime.now()


def register(uid: int, name: str):
    all_users.add(uid)
    if uid not in user_lang:
        user_lang[uid] = "ru"
    if uid not in user_currency:
        user_currency[uid] = "USD"  # по умолчанию доллары
    user_stats[uid]["name"] = name or str(uid)


def lang(uid: int) -> str:
    return user_lang.get(uid, "ru")


def currency(uid: int) -> str:
    """Валюта отображения пользователя"""
    return user_currency.get(uid, "USD")


def add_history(uid: int, frm: str, to: str, amount: float, result: float):
    ts = datetime.now().strftime("%d.%m %H:%M")
    user_history[uid].insert(0, {
        "frm": frm, "to": to,
        "amount": amount, "result": result, "ts": ts
    })
    user_history[uid] = user_history[uid][:10]
    user_stats[uid]["cnt"] += 1
    user_stats[uid]["last"] = ts


def delete_previous(uid: int, chat_id: int):
    """Удаляет предыдущее сообщение бота"""
    if uid in user_last_msg:
        try:
            bot.delete_message(chat_id, user_last_msg[uid])
        except Exception:
            pass


def send_and_track(uid: int, chat_id: int, text: str, reply_markup=None, **kwargs):
    """Отправляет сообщение и сохраняет его ID для последующего удаления"""
    delete_previous(uid, chat_id)
    msg = bot.send_message(chat_id, text, reply_markup=reply_markup, **kwargs)
    user_last_msg[uid] = msg.message_id
    return msg


# ─────────────────────────────────────────
#  ЛОКАЛИЗАЦИЯ
# ─────────────────────────────────────────
T = {
    "ru": {
        "welcome": (
            "Привет! Я Convert Bot\n\n"
            "Конвертирую крипту и фиат в реальном времени.\n\n"
            "Как использовать:\n"
            "  100 USD TON\n"
            "  0.5 BTC ETH\n"
            "  1000 RUB BTC\n"
            "  Просто: 100$\n\n"
            "Inline режим: @convertconvertbot 100 usd ton"
        ),
        # кнопки
        "b_conv": "💱 Конвертировать",
        "b_rates": "📊 Курсы",
        "b_top": "🔝 Топ крипто",
        "b_24h": "📈 За 24 часа",
        "b_cmp": "🔄 Сравнить",
        "b_fav": "⭐ Избранное",
        "b_port": "🎯 Портфель",
        "b_alr": "🔔 Алёрты",
        "b_hp": "📅 История цен",
        "b_news": "📰 Новости",
        "b_calc": "🧮 Калькулятор",
        "b_curr": "💰 Валюта",
        # конвертация
        "ask_conv": "Введите запрос:\n\n  100 USD TON\n  0.5 BTC ETH\n\n/cancel — отмена",
        "ask_cmp": "Введите 2 монеты:\n\n  BTC ETH\n  TON SOL\n\n/cancel — отмена",
        "ask_calc": "Формат: МОНЕТА ЦЕНА_ПОКУПКИ ТЕКУЩАЯ_ЦЕНА КОЛИЧЕСТВО\n\nПример: BTC 30000 65000 0.5\n\n/cancel — отмена",
        "ask_hp": "Введите монету (BTC, ETH, TON ...):\n\n/cancel — отмена",
        "cancelled": "Отменено.",
        "no_rates": "Курсы ещё загружаются. Попробуйте через несколько секунд.",
        "bad_query": "Не понял запрос. Пример: 100 USD TON",
        "bad_pair": "Не могу конвертировать эту пару.",
        "bad_coin": "Монета не найдена.",
        "cmp_bad": "Введите ровно 2 монеты. Пример: BTC ETH",
        "calc_bad": "Неверный формат. Пример: BTC 30000 65000 0.5",
        # курсы
        "rates_hdr": "КУРСЫ К {cur}\nОбновлено: {ts}\n\n",
        "top_hdr": "ТОП КРИПТОВАЛЮТ ({cur})\n{ts}\n\n",
        "h24_hdr": "ИЗМЕНЕНИЕ ЗА 24 ЧАСА ({cur})\n{ts}\n\n",
        "cmp_hdr": "СРАВНЕНИЕ {c1} vs {c2}\n{ts}\n\n",
        # результат конвертации
        "result": "Результат\n\n{a} {frm}  =  {r} {to}\n\nКурс: {ts}",
        "result_m": "{a} {frm} =\n",
        "result_ts": "\nКурс на {ts}",
        # история
        "hist_hdr": "ИСТОРИЯ КОНВЕРТАЦИЙ\n\n",
        "hist_empty": "История пуста.",
        # избранное
        "fav_hdr": "ИЗБРАННЫЕ ПАРЫ\n\n",
        "fav_empty": "Избранное пусто.\n\nДобавить: /fav BTC USD",
        "fav_hint": "Добавить пару: /fav BTC USD",
        "fav_added": "Пара {frm}/{to} добавлена в избранное.",
        "fav_dup": "Эта пара уже в избранном.",
        "fav_del": "Пара удалена.",
        "fav_cmd": "Формат: /fav BTC USD",
        # портфель
        "port_hdr": "МОЙ ПОРТФЕЛЬ ({cur})\nОбновлено: {ts}\n\n",
        "port_empty": "Портфель пуст.\n\nДобавить: /port BTC 0.5\nУдалить:  /port BTC 0",
        "port_total": "\nИТОГО: {total} {cur}",
        "port_add": "{coin} x{qty} добавлен в портфель.",
        "port_del": "{coin} удалён из портфеля.",
        "port_cmd": "Формат: /port BTC 0.5\nУдалить:  /port BTC 0",
        # алёрты
        "alr_hdr": "АКТИВНЫЕ АЛЁРТЫ\n\n",
        "alr_empty": "Алёртов нет.\n\nУстановить: /alert BTC > 70000",
        "alr_add": "Алёрт установлен:\n{coin} {op} {price} {cur}",
        "alr_del": "Алёрт удалён.",
        "alr_fire": "АЛЁРТ СРАБОТАЛ!\n\n{coin} достиг {price} {cur}\nТекущая цена: {cur} {cur}",
        "alr_cmd": "Формат: /alert BTC > 70000  (операторы > и <)",
        # история цен
        "hp_choose": "Выберите период:",
        "hp_hdr": "ИСТОРИЯ ЦЕН {coin} ({cur})\n{ts}\n\n",
        "hp_stat": "\nМин: {mn} {cur}   Макс: {mx} {cur}\nИзменение: {ch}%\nСейчас: {now} {cur}",
        "hp_err": "Не удалось загрузить данные.",
        # новости
        "news_channel": "📰 Подписывайтесь на наш Telegram канал для актуальных новостей:",
        "news_btn": "Перейти на канал",
        # калькулятор
        "calc": (
            "КАЛЬКУЛЯТОР ПРИБЫЛИ ({cur})\n\n"
            "{coin}\n"
            "Куплено:   {qty} шт по {buy} {cur}\n"
            "Вложено:   {inv} {cur}\n"
            "Сейчас:    {now} {cur}\n"
            "Прибыль:   {pnl} {cur}  ({pct}%)\n\n"
            "Цена {coin} сейчас: {cur_price} {cur}"
        ),
        # язык
        "lang_choose": "Выберите язык:",
        "lang_ok": "Язык изменён на Русский.",
        # валюта
        "curr_choose": "Выберите валюту для отображения:",
        "curr_usd": "🇺🇸 Доллар США (USD)",
        "curr_rub": "🇷🇺 Российский рубль (RUB)",
        "curr_eur": "🇪🇺 Евро (EUR)",
        "curr_ok": "Валюта изменена на {cur}",
        # админ
        "admin": (
            "СТАТИСТИКА БОТА\n\n"
            "Пользователей:    {users}\n"
            "Конвертаций:      {convs}\n"
            "Избранных пар:    {favs}\n"
            "Позиций порт.:    {ports}\n"
            "Активных алёртов: {alrs}\n"
            "Языки:  RU={ru}  EN={en}  UA={ua}\n"
            "Валюта: USD={usd} RUB={rub} EUR={eur}\n"
            "Онлайн с: {since}\n\n"
            "Топ-5 активных:\n{top}"
        ),
        "no_access": "Нет доступа.",
    },
    "en": {
        "welcome": (
            "Hello! I'm Convert Bot\n\n"
            "Real-time crypto & fiat converter.\n\n"
            "How to use:\n"
            "  100 USD TON\n"
            "  0.5 BTC ETH\n"
            "  Just: 100$\n\n"
            "Inline: @convertconvertbot 100 usd ton"
        ),
        "b_conv": "💱 Convert",
        "b_rates": "📊 Rates",
        "b_top": "🔝 Top crypto",
        "b_24h": "📈 24h Change",
        "b_cmp": "🔄 Compare",
        "b_fav": "⭐ Favorites",
        "b_port": "🎯 Portfolio",
        "b_alr": "🔔 Alerts",
        "b_hp": "📅 Price History",
        "b_news": "📰 News",
        "b_calc": "🧮 Calculator",
        "b_curr": "💰 Currency",
        "ask_conv": "Enter query:\n\n  100 USD TON\n  0.5 BTC ETH\n\n/cancel",
        "ask_cmp": "Enter 2 coins:\n\n  BTC ETH\n  TON SOL\n\n/cancel",
        "ask_calc": "Format: COIN BUY_PRICE CURRENT_PRICE AMOUNT\n\nExample: BTC 30000 65000 0.5\n\n/cancel",
        "ask_hp": "Enter coin (BTC, ETH, TON ...):\n\n/cancel",
        "cancelled": "Cancelled.",
        "no_rates": "Rates are loading. Try in a few seconds.",
        "bad_query": "Can't parse. Example: 100 USD TON",
        "bad_pair": "Cannot convert this pair.",
        "bad_coin": "Coin not found.",
        "cmp_bad": "Enter exactly 2 coins. Example: BTC ETH",
        "calc_bad": "Wrong format. Example: BTC 30000 65000 0.5",
        "rates_hdr": "RATES ({cur})\nUpdated: {ts}\n\n",
        "top_hdr": "TOP CRYPTOCURRENCIES ({cur})\n{ts}\n\n",
        "h24_hdr": "24H PRICE CHANGE ({cur})\n{ts}\n\n",
        "cmp_hdr": "COMPARE {c1} vs {c2}\n{ts}\n\n",
        "result": "Result\n\n{a} {frm}  =  {r} {to}\n\nRate at {ts}",
        "result_m": "{a} {frm} =\n",
        "result_ts": "\nRate at {ts}",
        "hist_hdr": "CONVERSION HISTORY\n\n",
        "hist_empty": "History is empty.",
        "fav_hdr": "FAVORITE PAIRS\n\n",
        "fav_empty": "No favorites.\n\nAdd: /fav BTC USD",
        "fav_hint": "Add pair: /fav BTC USD",
        "fav_added": "Pair {frm}/{to} added to favorites.",
        "fav_dup": "This pair is already in favorites.",
        "fav_del": "Pair removed.",
        "fav_cmd": "Format: /fav BTC USD",
        "port_hdr": "MY PORTFOLIO ({cur})\nUpdated: {ts}\n\n",
        "port_empty": "Portfolio is empty.\n\nAdd: /port BTC 0.5\nRemove: /port BTC 0",
        "port_total": "\nTOTAL: {total} {cur}",
        "port_add": "{coin} x{qty} added to portfolio.",
        "port_del": "{coin} removed from portfolio.",
        "port_cmd": "Format: /port BTC 0.5\nRemove: /port BTC 0",
        "alr_hdr": "ACTIVE ALERTS\n\n",
        "alr_empty": "No alerts.\n\nSet one: /alert BTC > 70000",
        "alr_add": "Alert set:\n{coin} {op} {price} {cur}",
        "alr_del": "Alert removed.",
        "alr_fire": "ALERT TRIGGERED!\n\n{coin} reached {price} {cur}\nCurrent price: {cur} {cur}",
        "alr_cmd": "Format: /alert BTC > 70000  (operators > and <)",
        "hp_choose": "Choose period:",
        "hp_hdr": "PRICE HISTORY {coin} ({cur})\n{ts}\n\n",
        "hp_stat": "\nMin: {mn} {cur}   Max: {mx} {cur}\nChange: {ch}%\nNow: {now} {cur}",
        "hp_err": "Failed to load data.",
        "news_channel": "📰 Subscribe to our Telegram channel for latest news:",
        "news_btn": "Go to channel",
        "calc": (
            "PROFIT CALCULATOR ({cur})\n\n"
            "{coin}\n"
            "Bought:    {qty} pcs at {buy} {cur}\n"
            "Invested:  {inv} {cur}\n"
            "Worth now: {now} {cur}\n"
            "Profit:    {pnl} {cur}  ({pct}%)\n\n"
            "{coin} price now: {cur_price} {cur}"
        ),
        "lang_choose": "Choose language:",
        "lang_ok": "Language changed to English.",
        "curr_choose": "Choose display currency:",
        "curr_usd": "🇺🇸 US Dollar (USD)",
        "curr_rub": "🇷🇺 Russian Ruble (RUB)",
        "curr_eur": "🇪🇺 Euro (EUR)",
        "curr_ok": "Currency changed to {cur}",
        "admin": (
            "BOT STATISTICS\n\n"
            "Users:          {users}\n"
            "Conversions:    {convs}\n"
            "Saved pairs:    {favs}\n"
            "Portfolio pos.: {ports}\n"
            "Active alerts:  {alrs}\n"
            "Languages: RU={ru}  EN={en}  UA={ua}\n"
            "Currency: USD={usd} RUB={rub} EUR={eur}\n"
            "Online since: {since}\n\n"
            "Top 5:\n{top}"
        ),
        "no_access": "Access denied.",
    },
    "ua": {
        "welcome": (
            "Привіт! Я Convert Bot\n\n"
            "Конвертую крипту та фіат у реальному часі.\n\n"
            "Як користуватись:\n"
            "  100 USD TON\n"
            "  0.5 BTC ETH\n"
            "  Просто: 100$\n\n"
            "Inline: @convertconvertbot 100 usd ton"
        ),
        "b_conv": "💱 Конвертувати",
        "b_rates": "📊 Курси",
        "b_top": "🔝 Топ крипто",
        "b_24h": "📈 За 24 год",
        "b_cmp": "🔄 Порівняти",
        "b_fav": "⭐ Обране",
        "b_port": "🎯 Портфель",
        "b_alr": "🔔 Алерти",
        "b_hp": "📅 Історія цін",
        "b_news": "📰 Новини",
        "b_calc": "🧮 Калькулятор",
        "b_curr": "💰 Валюта",
        "ask_conv": "Введіть запит:\n\n  100 USD TON\n  0.5 BTC ETH\n\n/cancel — скасування",
        "ask_cmp": "Введіть 2 монети:\n\n  BTC ETH\n  TON SOL\n\n/cancel",
        "ask_calc": "Формат: МОНЕТА ЦІНА_КУПІВЛІ ПОТОЧНА_ЦІНА КІЛЬКІСТЬ\n\nПриклад: BTC 30000 65000 0.5\n\n/cancel",
        "ask_hp": "Введіть монету (BTC, ETH, TON ...):\n\n/cancel",
        "cancelled": "Скасовано.",
        "no_rates": "Курси ще завантажуються. Спробуйте через кілька секунд.",
        "bad_query": "Не зрозумів. Приклад: 100 USD TON",
        "bad_pair": "Не можу конвертувати цю пару.",
        "bad_coin": "Монету не знайдено.",
        "cmp_bad": "Введіть 2 монети. Приклад: BTC ETH",
        "calc_bad": "Невірний формат. Приклад: BTC 30000 65000 0.5",
        "rates_hdr": "КУРСИ ДО {cur}\nОновлено: {ts}\n\n",
        "top_hdr": "ТОП КРИПТОВАЛЮТ ({cur})\n{ts}\n\n",
        "h24_hdr": "ЗМІНА ЗА 24 ГОДИНИ ({cur})\n{ts}\n\n",
        "cmp_hdr": "ПОРІВНЯННЯ {c1} vs {c2}\n{ts}\n\n",
        "result": "Результат\n\n{a} {frm}  =  {r} {to}\n\nКурс: {ts}",
        "result_m": "{a} {frm} =\n",
        "result_ts": "\nКурс на {ts}",
        "hist_hdr": "ІСТОРІЯ КОНВЕРТАЦІЙ\n\n",
        "hist_empty": "Історія порожня.",
        "fav_hdr": "ОБРАНІ ПАРИ\n\n",
        "fav_empty": "Обране порожнє.\n\nДодати: /fav BTC USD",
        "fav_hint": "Додати пару: /fav BTC USD",
        "fav_added": "Пара {frm}/{to} додана до обраного.",
        "fav_dup": "Ця пара вже є в обраному.",
        "fav_del": "Пару видалено.",
        "fav_cmd": "Формат: /fav BTC USD",
        "port_hdr": "МІЙ ПОРТФЕЛЬ ({cur})\nОновлено: {ts}\n\n",
        "port_empty": "Портфель порожній.\n\nДодати: /port BTC 0.5\nВидалити: /port BTC 0",
        "port_total": "\nРАЗОМ: {total} {cur}",
        "port_add": "{coin} x{qty} додано до портфеля.",
        "port_del": "{coin} видалено з портфеля.",
        "port_cmd": "Формат: /port BTC 0.5\nВидалити: /port BTC 0",
        "alr_hdr": "АКТИВНІ АЛЕРТИ\n\n",
        "alr_empty": "Алертів немає.\n\nВстановити: /alert BTC > 70000",
        "alr_add": "Алерт встановлено:\n{coin} {op} {price} {cur}",
        "alr_del": "Алерт видалено.",
        "alr_fire": "АЛЕРТ СПРАЦЮВАВ!\n\n{coin} досяг {price} {cur}\nПоточна ціна: {cur} {cur}",
        "alr_cmd": "Формат: /alert BTC > 70000  (оператори > та <)",
        "hp_choose": "Оберіть період:",
        "hp_hdr": "ІСТОРІЯ ЦІН {coin} ({cur})\n{ts}\n\n",
        "hp_stat": "\nМін: {mn} {cur}   Макс: {mx} {cur}\nЗміна: {ch}%\nЗараз: {now} {cur}",
        "hp_err": "Не вдалося завантажити дані.",
        "news_channel": "📰 Підписуйтесь на наш Telegram канал для актуальних новин:",
        "news_btn": "Перейти на канал",
        "calc": (
            "КАЛЬКУЛЯТОР ПРИБУТКУ ({cur})\n\n"
            "{coin}\n"
            "Куплено:   {qty} шт по {buy} {cur}\n"
            "Вкладено:  {inv} {cur}\n"
            "Зараз:     {now} {cur}\n"
            "Прибуток:  {pnl} {cur}  ({pct}%)\n\n"
            "Ціна {coin} зараз: {cur_price} {cur}"
        ),
        "lang_choose": "Оберіть мову:",
        "lang_ok": "Мову змінено на Українська.",
        "curr_choose": "Оберіть валюту відображення:",
        "curr_usd": "🇺🇸 Долар США (USD)",
        "curr_rub": "🇷🇺 Російський рубль (RUB)",
        "curr_eur": "🇪🇺 Євро (EUR)",
        "curr_ok": "Валюту змінено на {cur}",
        "admin": (
            "СТАТИСТИКА БОТА\n\n"
            "Користувачів:    {users}\n"
            "Конвертацій:     {convs}\n"
            "Обраних пар:     {favs}\n"
            "Позицій порт.:   {ports}\n"
            "Активних алертів:{alrs}\n"
            "Мови: RU={ru}  EN={en}  UA={ua}\n"
            "Валюта: USD={usd} RUB={rub} EUR={eur}\n"
            "Онлайн з: {since}\n\n"
            "Топ-5:\n{top}"
        ),
        "no_access": "Немає доступу.",
    },
}

LANG_NAMES = {"ru": "Русский", "en": "English", "ua": "Українська"}
CURR_SYMBOLS = {"USD": "$", "EUR": "€", "RUB": "₽"}


def t(uid: int, key: str, **kw) -> str:
    """Получить строку локализации."""
    lg = lang(uid)
    text = T.get(lg, T["ru"]).get(key, T["ru"].get(key, key))

    # Добавляем валюту пользователя в параметры, если её нет
    if "cur" not in kw and key not in ["curr_choose", "curr_ok", "lang_choose", "lang_ok"]:
        kw["cur"] = currency(uid)

    if kw:
        try:
            return text.format(**kw)
        except Exception:
            return text
    return text


# ─────────────────────────────────────────
#  КУРСЫ
# ─────────────────────────────────────────
rates: dict = {}  # {"BTC": {"USD":..., "EUR":..., "RUB":...}, ...}
ch24: dict = {}  # {"BTC": 2.34, ...}
updated: datetime = None


def _fetch_rates():
    global rates, ch24, updated
    cg_ids = ",".join(v for v in COINS.values() if v)
    url = (
        "https://api.coingecko.com/api/v3/simple/price"
        f"?ids={cg_ids}&vs_currencies=usd,eur,rub&include_24hr_change=true"
    )
    try:
        r = requests.get(url, timeout=20, headers={"Accept": "application/json"})
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log.error("fetch_rates error: %s", e)
        return

    new_rates = {}
    new_ch24 = {}
    for sym, cg_id in COINS.items():
        if cg_id and cg_id in data:
            row = data[cg_id]
            new_rates[sym] = {
                "USD": float(row.get("usd") or 0),
                "EUR": float(row.get("eur") or 0),
                "RUB": float(row.get("rub") or 0),
            }
            new_ch24[sym] = float(row.get("usd_24h_change") or 0)

    if not new_rates:
        log.warning("fetch_rates: empty response")
        return

    # Фиат через USDT для большей точности
    usdt = new_rates.get("USDT", {})
    er = usdt.get("EUR") or 0.92
    rr = usdt.get("RUB") or 90.0

    # Точные курсы фиата
    new_rates["USD"] = {"USD": 1.0, "EUR": er, "RUB": rr}
    new_rates["EUR"] = {"USD": 1 / er if er else 1.09, "EUR": 1.0, "RUB": rr / er if er else 98.0}
    new_rates["RUB"] = {"USD": 1 / rr if rr else 0.011, "EUR": er / rr if rr else 0.0094, "RUB": 1.0}

    rates = new_rates
    ch24 = new_ch24
    updated = datetime.now()
    log.info("rates updated: %s coins at %s", len(new_rates), updated.strftime("%H:%M:%S"))


def _rates_loop():
    while True:
        time.sleep(RATE_UPDATE_SEC)
        _fetch_rates()


def ts() -> str:
    return updated.strftime("%H:%M:%S") if updated else "—"


def convert(amount: float, frm: str, to: str):
    frm, to = frm.upper(), to.upper()
    if frm not in rates or to not in rates:
        return None
    usd = amount * rates[frm]["USD"]
    if to == "USD":
        return usd
    if to in FIAT:
        return usd * rates["USD"][to]
    p = rates[to]["USD"]
    return (usd / p) if p else None


def get_price_in_currency(coin: str, cur: str) -> float:
    """Получить цену монеты в указанной валюте"""
    if coin not in rates or cur not in rates[coin]:
        return 0
    return rates[coin][cur]


def fmt(n, cur: str = None) -> str:
    """Форматирование числа с валютой"""
    if n is None:
        return "—"
    n = float(n)
    if n == 0:
        return "0"

    # Форматирование в зависимости от размера
    if n >= 1_000_000:
        return f"{n:,.2f}"
    if n >= 1_000:
        return f"{n:,.4f}"
    if n >= 1:
        return f"{n:.6f}"
    if n >= 0.01:
        return f"{n:.8f}"
    s = f"{n:.12f}".rstrip("0").rstrip(".")
    return s


ALIASES = {"$": "USD", "€": "EUR", "₽": "RUB", "ТОН": "TON", "БТК": "BTC"}


def parse_query(text: str):
    """Парсит '100 USD TON' → (100.0, 'USD', 'TON')."""
    t2 = text.strip().upper()
    for a, s in ALIASES.items():
        t2 = t2.replace(a, f" {s} ")
    tokens = t2.split()
    amount = None
    curs = []
    for tok in tokens:
        try:
            amount = float(tok.replace(",", "."))
        except ValueError:
            if tok in COINS:
                curs.append(tok)
    if amount is None:
        return None, None, None
    return amount, (curs[0] if curs else "USD"), (curs[1] if len(curs) >= 2 else None)


# ─────────────────────────────────────────
#  ИСТОРИЯ ЦЕН
# ─────────────────────────────────────────
def _fetch_history(cg_id: str, days: int) -> list:
    url = (
        f"https://api.coingecko.com/api/v3/coins/{cg_id}/market_chart"
        f"?vs_currency=usd&days={days}&interval=daily"
    )
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        prices = r.json().get("prices", [])
        return [(datetime.fromtimestamp(p[0] / 1000).strftime("%d.%m"), float(p[1]))
                for p in prices]
    except Exception as e:
        log.error("price history: %s", e)
        return []


def _build_chart(prices: list, cur: str) -> str:
    if not prices:
        return "Нет данных"
    mn = min(p for _, p in prices)
    mx = max(p for _, p in prices)
    rng = mx - mn or 1
    bar = "▁▂▃▄▅▆▇█"
    lines = []
    for date, price in prices[-14:]:
        idx = int((price - mn) / rng * 7)
        lines.append(f"{date}  {bar[idx]}  {fmt(price)} {cur}")
    return "\n".join(lines)


# ─────────────────────────────────────────
#  НОВОСТИ
# ─────────────────────────────────────────
NEWS_CHANNEL_URL = "https://t.me/ConvertConvert"


def send_news_channel_link(cid: int, uid: int):
    """Отправляет ссылку на Telegram канал с новостями"""
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton(
        text=t(uid, "news_btn"),
        url=NEWS_CHANNEL_URL
    ))

    send_and_track(uid, cid, t(uid, "news_channel"), reply_markup=keyboard)


# ─────────────────────────────────────────
#  АЛЁРТЫ — фоновая проверка
# ─────────────────────────────────────────
def _alert_loop():
    while True:
        time.sleep(60)
        if not rates:
            continue
        for uid, alerts in list(user_alerts.items()):
            for a in list(alerts):
                if not a.get("active"):
                    continue
                cur = rates.get(a["coin"], {}).get("USD", 0)
                fired = (a["op"] == ">" and cur >= a["price"]) or \
                        (a["op"] == "<" and cur <= a["price"])
                if fired:
                    a["active"] = False
                    try:
                        bot.send_message(uid, t(uid, "alr_fire",
                                                coin=a["coin"],
                                                price=fmt(a["price"]),
                                                cur=fmt(cur)))
                    except Exception:
                        pass


# ─────────────────────────────────────────
#  КЛАВИАТУРЫ
# ─────────────────────────────────────────
def main_kb(uid: int) -> types.ReplyKeyboardMarkup:
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keys = ["b_conv", "b_rates", "b_top", "b_24h", "b_cmp", "b_fav",
            "b_port", "b_alr", "b_hp", "b_news", "b_calc", "b_curr"]
    row = []
    for k in keys:
        row.append(t(uid, k))
        if len(row) == 2:
            kb.row(*row)
            row = []
    if row:
        kb.row(*row)
    return kb


def lang_kb() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("🇷🇺 Русский", callback_data="lang|ru"),
        types.InlineKeyboardButton("🇬🇧 English", callback_data="lang|en"),
        types.InlineKeyboardButton("🇺🇦 Українська", callback_data="lang|ua"),
    )
    return kb


def currency_kb(uid: int) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton(t(uid, "curr_usd"), callback_data="curr|USD"),
        types.InlineKeyboardButton(t(uid, "curr_eur"), callback_data="curr|EUR"),
    )
    kb.row(
        types.InlineKeyboardButton(t(uid, "curr_rub"), callback_data="curr|RUB"),
    )
    return kb


def fav_kb(uid: int) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    for i, (frm, to) in enumerate(user_favorites[uid]):
        r = convert(1, frm, to)
        cur = currency(uid)
        if r and to in rates and cur in rates[to]:
            val = f"  = {fmt(r * rates[to][cur])} {cur}"
        else:
            val = ""
        lbl = f"{frm} -> {to}{val}"
        kb.row(
            types.InlineKeyboardButton(lbl, callback_data=f"fq|{i}"),
            types.InlineKeyboardButton("🗑", callback_data=f"fd|{i}"),
        )
    return kb


def alert_kb(uid: int) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    for i, a in enumerate(user_alerts[uid]):
        status = "✅" if a["active"] else "❌"
        lbl = f"{status} {a['coin']} {a['op']} {fmt(a['price'])} {currency(uid)}"
        kb.row(
            types.InlineKeyboardButton(lbl, callback_data="noop"),
            types.InlineKeyboardButton("🗑", callback_data=f"ad|{i}"),
        )
    return kb


def hp_kb(coin: str) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("7 дней", callback_data=f"hp|7|{coin}"),
        types.InlineKeyboardButton("30 дней", callback_data=f"hp|30|{coin}"),
    )
    return kb


# ─────────────────────────────────────────
#  ОТПРАВКА РАЗДЕЛОВ
# ─────────────────────────────────────────
def send_rates(cid: int, uid: int):
    if not rates:
        send_and_track(uid, cid, t(uid, "no_rates"), reply_markup=main_kb(uid))
        return

    cur = currency(uid)
    coins = ["BTC", "ETH", "TON", "BNB", "SOL", "XRP", "ADA", "DOGE",
             "TRX", "DOT", "MATIC", "LTC", "AVAX"]
    lines = [t(uid, "rates_hdr", ts=ts())]

    for c in coins:
        if c not in rates:
            continue
        price = get_price_in_currency(c, cur)
        chg = ch24.get(c, 0)
        sgn = "+" if chg >= 0 else ""
        arr = "▲" if chg >= 0 else "▼"
        lines.append(f"{c:<6}  {fmt(price)} {cur:<4}  {arr}{sgn}{chg:.2f}%")

    send_and_track(uid, cid, "\n".join(lines), reply_markup=main_kb(uid))


def send_top(cid: int, uid: int):
    if not rates:
        send_and_track(uid, cid, t(uid, "no_rates"), reply_markup=main_kb(uid))
        return

    cur = currency(uid)
    coins = ["BTC", "ETH", "TON", "BNB", "SOL", "USDT", "XRP", "ADA", "DOGE",
             "TRX", "DOT", "MATIC", "LTC", "AVAX", "SHIB", "LINK", "UNI", "ATOM", "XLM"]
    lines = [t(uid, "top_hdr", ts=ts())]

    for i, c in enumerate(coins, 1):
        if c not in rates:
            continue
        price = get_price_in_currency(c, cur)
        chg = ch24.get(c, 0)
        sgn = "+" if chg >= 0 else ""
        arr = "▲" if chg >= 0 else "▼"
        lines.append(f"{i:>2}. {c:<6}  {fmt(price)} {cur:<4}  {arr}{sgn}{chg:.2f}%")

    send_and_track(uid, cid, "\n".join(lines), reply_markup=main_kb(uid))


def send_24h(cid: int, uid: int):
    if not ch24:
        send_and_track(uid, cid, t(uid, "no_rates"), reply_markup=main_kb(uid))
        return

    cur = currency(uid)
    coins = ["BTC", "ETH", "TON", "BNB", "SOL", "XRP", "ADA", "DOGE",
             "TRX", "DOT", "MATIC", "LTC", "AVAX", "SHIB", "LINK"]
    sc = sorted([c for c in coins if c in ch24],
                key=lambda c: ch24[c], reverse=True)
    lines = [t(uid, "h24_hdr", ts=ts())]

    for c in sc:
        price = get_price_in_currency(c, cur)
        chg = ch24[c]
        sgn = "+" if chg >= 0 else ""
        arr = "▲" if chg >= 0 else "▼"
        lines.append(f"{arr} {c:<6}  {fmt(price)} {cur:<4}  {sgn}{chg:.2f}%")

    send_and_track(uid, cid, "\n".join(lines), reply_markup=main_kb(uid))


def send_compare(cid: int, uid: int, c1: str, c2: str):
    if not rates:
        send_and_track(uid, cid, t(uid, "no_rates"), reply_markup=main_kb(uid))
        return

    cur = currency(uid)
    p1 = get_price_in_currency(c1, cur)
    p2 = get_price_in_currency(c2, cur)
    ch1 = ch24.get(c1, 0);
    s1 = "+" if ch1 >= 0 else "";
    a1 = "▲" if ch1 >= 0 else "▼"
    ch2 = ch24.get(c2, 0);
    s2 = "+" if ch2 >= 0 else "";
    a2 = "▲" if ch2 >= 0 else "▼"
    c12 = convert(1, c1, c2);
    c21 = convert(1, c2, c1)
    ratio = (p1 / p2) if p2 else 0

    note = (f"{c1} дороже {c2} в {ratio:.2f}x" if ratio > 1
            else f"{c2} дороже {c1} в {1 / ratio:.2f}x" if 0 < ratio < 1
    else "")

    text = (
            t(uid, "cmp_hdr", c1=c1, c2=c2, ts=ts()) +
            f"{c1}\n"
            f"  Цена:  {fmt(p1)} {cur}\n"
            f"  24ч:   {a1}{s1}{ch1:.2f}%\n\n"
            f"{c2}\n"
            f"  Цена:  {fmt(p2)} {cur}\n"
            f"  24ч:   {a2}{s2}{ch2:.2f}%\n\n"
            f"1 {c1} = {fmt(c12)} {c2}\n"
            f"1 {c2} = {fmt(c21)} {c1}\n"
    )
    if note:
        text += f"\n{note}"

    send_and_track(uid, cid, text, reply_markup=main_kb(uid))


def send_favorites(cid: int, uid: int):
    favs = user_favorites[uid]
    if not favs:
        send_and_track(uid, cid, t(uid, "fav_empty"), reply_markup=main_kb(uid))
        return

    cur = currency(uid)
    lines = [t(uid, "fav_hdr")]
    for i, (frm, to) in enumerate(favs, 1):
        r = convert(1, frm, to)
        if r and to in rates and cur in rates[to]:
            val = f"  =  {fmt(r * rates[to][cur])} {cur}"
        else:
            val = ""
        lines.append(f"{i}. {frm} -> {to}{val}")
    lines.append(f"\n{t(uid, 'fav_hint')}")

    send_and_track(uid, cid, "\n".join(lines), reply_markup=fav_kb(uid))


def send_portfolio(cid: int, uid: int):
    port = user_portfolio[uid]
    if not port:
        send_and_track(uid, cid, t(uid, "port_empty"), reply_markup=main_kb(uid))
        return

    cur = currency(uid)
    lines = [t(uid, "port_hdr", ts=ts())]
    total = 0.0

    for coin, qty in port.items():
        if coin not in rates or cur not in rates[coin]:
            continue
        value = qty * rates[coin][cur]
        chg = ch24.get(coin, 0)
        sgn = "+" if chg >= 0 else ""
        arr = "▲" if chg >= 0 else "▼"
        total += value
        lines.append(
            f"{coin} x{fmt(qty)}\n"
            f"  {fmt(value)} {cur}   {arr}{sgn}{chg:.2f}%"
        )

    lines.append(t(uid, "port_total", total=fmt(total)))
    lines.append("\n/port BTC 0.5 — добавить   /port BTC 0 — удалить")

    send_and_track(uid, cid, "\n".join(lines), reply_markup=main_kb(uid))


def send_alerts(cid: int, uid: int):
    alerts = user_alerts[uid]
    if not alerts:
        send_and_track(uid, cid, t(uid, "alr_empty"), reply_markup=main_kb(uid))
        return

    cur = currency(uid)
    lines = [t(uid, "alr_hdr")]
    for i, a in enumerate(alerts, 1):
        status = "✅ Активен" if a["active"] else "❌ Сработал"
        price_in_cur = a["price"]
        if a["coin"] in rates and "USD" in rates[a["coin"]] and cur != "USD":
            # Конвертируем цену алерта в валюту пользователя
            usd_price = a["price"]
            price_in_cur = usd_price * rates["USD"][cur]

        lines.append(f"{i}. {a['coin']} {a['op']} {fmt(price_in_cur)} {cur}  [{status}]")
    lines.append("\n/alert BTC > 70000 — добавить")

    send_and_track(uid, cid, "\n".join(lines), reply_markup=alert_kb(uid))


def process_convert(cid: int, uid: int, text: str):
    if not rates:
        send_and_track(uid, cid, t(uid, "no_rates"), reply_markup=main_kb(uid))
        return

    amount, frm, to = parse_query(text)
    if amount is None:
        send_and_track(uid, cid, t(uid, "bad_query"), reply_markup=main_kb(uid))
        return

    if to:
        r = convert(amount, frm, to)
        if r is None:
            send_and_track(uid, cid, t(uid, "bad_pair"), reply_markup=main_kb(uid))
            return

        add_history(uid, frm, to, amount, r)
        send_and_track(uid, cid,
                       t(uid, "result", a=fmt(amount), frm=frm, r=fmt(r), to=to, ts=ts()),
                       reply_markup=main_kb(uid))
    else:
        cur = currency(uid)
        targets = [c for c in ["TON", "BTC", "ETH", "BNB", "SOL", "USDT", "USD", "EUR", "RUB"] if c != frm]
        lines = [t(uid, "result_m", a=fmt(amount), frm=frm)]

        for c in targets:
            r = convert(amount, frm, c)
            if r is not None:
                if c in rates and cur in rates[c]:
                    r_in_cur = r * rates[c][cur]
                    lines.append(f"  {c:<6}  {fmt(r)} = {fmt(r_in_cur)} {cur}")
                else:
                    lines.append(f"  {c:<6}  {fmt(r)}")

        lines.append(t(uid, "result_ts", ts=ts()))

        first = next((c for c in targets if convert(amount, frm, c) is not None), None)
        if first:
            add_history(uid, frm, first, amount, convert(amount, frm, first))

        send_and_track(uid, cid, "\n".join(lines), reply_markup=main_kb(uid))


def process_profit(cid: int, uid: int, text: str):
    parts = text.upper().split()
    try:
        coin = parts[0]
        buy = float(parts[1].replace(",", "."))
        sell = float(parts[2].replace(",", "."))
        qty = float(parts[3].replace(",", ".")) if len(parts) > 3 else 1.0
        assert coin in COINS and buy > 0 and sell > 0 and qty > 0
    except Exception:
        send_and_track(uid, cid, t(uid, "calc_bad"), reply_markup=main_kb(uid))
        return

    cur = currency(uid)
    inv = buy * qty
    now = sell * qty
    pnl = now - inv
    pct = (pnl / inv * 100) if inv else 0
    sign = "+" if pnl >= 0 else ""

    # Текущая цена в валюте пользователя
    cur_price = 0
    if coin in rates and cur in rates[coin]:
        cur_price = rates[coin][cur]

    send_and_track(uid, cid,
                   t(uid, "calc",
                     coin=coin,
                     qty=fmt(qty),
                     buy=fmt(buy),
                     inv=fmt(inv),
                     now=fmt(now),
                     pnl=f"{sign}{fmt(pnl)}",
                     pct=f"{sign}{pct:.2f}",
                     cur_price=fmt(cur_price)),
                   reply_markup=main_kb(uid))


# ─────────────────────────────────────────
#  КОМАНДЫ
# ─────────────────────────────────────────
@bot.message_handler(commands=["start"])
def cmd_start(msg: types.Message):
    uid = msg.from_user.id
    register(uid, msg.from_user.full_name or "")
    user_state.pop(uid, None)
    delete_previous(uid, msg.chat.id)
    bot.send_message(msg.chat.id, t(uid, "welcome"), reply_markup=main_kb(uid))


@bot.message_handler(commands=["help"])
def cmd_help(msg: types.Message):
    uid = msg.from_user.id
    register(uid, msg.from_user.full_name or "")
    delete_previous(uid, msg.chat.id)
    bot.send_message(msg.chat.id,
                     "Команды:\n"
                     "  /fav BTC USD         — добавить в избранное\n"
                     "  /port BTC 0.5        — добавить в портфель\n"
                     "  /port BTC 0          — удалить из портфеля\n"
                     "  /alert BTC > 70000   — алёрт на цену\n"
                     "  /admin               — статистика бота\n"
                     "  /cancel              — отмена\n\n"
                     "Конвертация:\n"
                     "  100 USD TON\n"
                     "  0.5 BTC ETH\n"
                     "  100$",
                     reply_markup=main_kb(uid))


@bot.message_handler(commands=["cancel"])
def cmd_cancel(msg: types.Message):
    uid = msg.from_user.id
    user_state.pop(uid, None)
    delete_previous(uid, msg.chat.id)
    bot.send_message(msg.chat.id, t(uid, "cancelled"), reply_markup=main_kb(uid))


@bot.message_handler(commands=["fav"])
def cmd_fav(msg: types.Message):
    uid = msg.from_user.id
    register(uid, msg.from_user.full_name or "")
    parts = msg.text.upper().split()

    if len(parts) < 3 or parts[1] not in COINS or parts[2] not in COINS:
        bot.send_message(msg.chat.id, t(uid, "fav_cmd"))
        return

    frm, to = parts[1], parts[2]
    if (frm, to) in user_favorites[uid]:
        bot.send_message(msg.chat.id, t(uid, "fav_dup"))
        return

    user_favorites[uid].append((frm, to))
    delete_previous(uid, msg.chat.id)
    bot.send_message(msg.chat.id, t(uid, "fav_added", frm=frm, to=to), reply_markup=main_kb(uid))


@bot.message_handler(commands=["port"])
def cmd_port(msg: types.Message):
    uid = msg.from_user.id
    register(uid, msg.from_user.full_name or "")
    parts = msg.text.upper().split()

    if len(parts) < 3 or parts[1] not in COINS or parts[1] in FIAT:
        bot.send_message(msg.chat.id, t(uid, "port_cmd"))
        return

    coin = parts[1]
    try:
        qty = float(parts[2].replace(",", "."))
    except ValueError:
        bot.send_message(msg.chat.id, t(uid, "port_cmd"))
        return

    delete_previous(uid, msg.chat.id)

    if qty <= 0:
        user_portfolio[uid].pop(coin, None)
        bot.send_message(msg.chat.id, t(uid, "port_del", coin=coin), reply_markup=main_kb(uid))
    else:
        user_portfolio[uid][coin] = qty
        bot.send_message(msg.chat.id, t(uid, "port_add", coin=coin, qty=fmt(qty)), reply_markup=main_kb(uid))


@bot.message_handler(commands=["alert"])
def cmd_alert(msg: types.Message):
    uid = msg.from_user.id
    register(uid, msg.from_user.full_name or "")
    parts = msg.text.upper().split()

    if len(parts) < 4 or parts[1] not in COINS or parts[2] not in (">", "<"):
        bot.send_message(msg.chat.id, t(uid, "alr_cmd"))
        return

    try:
        price = float(parts[3].replace(",", "."))
    except ValueError:
        bot.send_message(msg.chat.id, t(uid, "alr_cmd"))
        return

    user_alerts[uid].append({"coin": parts[1], "op": parts[2], "price": price, "active": True})
    delete_previous(uid, msg.chat.id)
    bot.send_message(msg.chat.id,
                     t(uid, "alr_add", coin=parts[1], op=parts[2], price=fmt(price)),
                     reply_markup=main_kb(uid))


@bot.message_handler(commands=["admin"])
def cmd_admin(msg: types.Message):
    uid = msg.from_user.id
    if uid not in ADMIN_IDS:
        bot.send_message(msg.chat.id, t(uid, "no_access"))
        return

    convs = sum(s["cnt"] for s in user_stats.values())
    favs = sum(len(f) for f in user_favorites.values())
    ports = sum(len(p) for p in user_portfolio.values())
    alrs = sum(sum(1 for a in al if a["active"]) for al in user_alerts.values())
    lc = {l: sum(1 for v in user_lang.values() if v == l) for l in ("ru", "en", "ua")}
    curr_stats = {c: sum(1 for v in user_currency.values() if v == c) for c in ("USD", "EUR", "RUB")}

    top5 = sorted(user_stats.items(), key=lambda x: x[1]["cnt"], reverse=True)[:5]
    tops = "\n".join(f"  {i}. {s.get('name', str(u))} — {s['cnt']}"
                     for i, (u, s) in enumerate(top5, 1)) or "  —"

    delete_previous(uid, msg.chat.id)
    bot.send_message(msg.chat.id,
                     t(uid, "admin",
                       users=len(all_users), convs=convs, favs=favs, ports=ports, alrs=alrs,
                       ru=lc.get("ru", 0), en=lc.get("en", 0), ua=lc.get("ua", 0),
                       usd=curr_stats.get("USD", 0), rub=curr_stats.get("RUB", 0), eur=curr_stats.get("EUR", 0),
                       since=bot_start_time.strftime("%d.%m.%Y %H:%M"),
                       top=tops))


@bot.message_handler(commands=["broadcast"])
def cmd_broadcast(msg: types.Message):
    uid = msg.from_user.id
    if uid not in ADMIN_IDS:
        bot.send_message(msg.chat.id, t(uid, "no_access"))
        return

    text = msg.text.replace("/broadcast", "", 1).strip()
    if not text:
        bot.send_message(msg.chat.id, "Формат: /broadcast Текст")
        return

    ok = 0
    for u in list(all_users):
        try:
            bot.send_message(u, f"Сообщение от администратора:\n\n{text}")
            ok += 1
        except Exception:
            pass

    bot.send_message(msg.chat.id, f"Отправлено: {ok} из {len(all_users)}")


# ─────────────────────────────────────────
#  CALLBACK HANDLERS
# ─────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data.startswith("lang|"))
def cb_lang(call: types.CallbackQuery):
    uid = call.from_user.id
    code = call.data.split("|")[1]

    if code in T:
        user_lang[uid] = code

    bot.answer_callback_query(call.id)
    delete_previous(uid, call.message.chat.id)
    bot.send_message(call.message.chat.id, t(uid, "lang_ok"), reply_markup=main_kb(uid))


@bot.callback_query_handler(func=lambda c: c.data.startswith("curr|"))
def cb_currency(call: types.CallbackQuery):
    uid = call.from_user.id
    code = call.data.split("|")[1]

    if code in ["USD", "EUR", "RUB"]:
        user_currency[uid] = code

    bot.answer_callback_query(call.id, t(uid, "curr_ok", cur=code))
    delete_previous(uid, call.message.chat.id)
    bot.send_message(call.message.chat.id, t(uid, "curr_ok", cur=code), reply_markup=main_kb(uid))


@bot.callback_query_handler(func=lambda c: c.data.startswith("fq|"))
def cb_fav_quick(call: types.CallbackQuery):
    uid = call.from_user.id
    bot.answer_callback_query(call.id)

    try:
        idx = int(call.data.split("|")[1])
        frm, to = user_favorites[uid][idx]
    except (IndexError, ValueError):
        return

    r = convert(1, frm, to)
    if r is None:
        bot.send_message(call.message.chat.id, t(uid, "bad_pair"))
        return

    cur = currency(uid)
    text = f"1 {frm}  =  {fmt(r)} {to}"
    if to in rates and cur in rates[to]:
        text += f"  =  {fmt(r * rates[to][cur])} {cur}"
    text += f"\nКурс на {ts()}"

    send_and_track(uid, call.message.chat.id, text, reply_markup=main_kb(uid))


@bot.callback_query_handler(func=lambda c: c.data.startswith("fd|"))
def cb_fav_del(call: types.CallbackQuery):
    uid = call.from_user.id

    try:
        idx = int(call.data.split("|")[1])
        user_favorites[uid].pop(idx)
    except (IndexError, ValueError):
        pass

    bot.answer_callback_query(call.id, t(uid, "fav_del"))

    if user_favorites[uid]:
        try:
            bot.edit_message_reply_markup(
                call.message.chat.id, call.message.message_id, reply_markup=fav_kb(uid))
        except Exception:
            pass
    else:
        try:
            bot.edit_message_text(t(uid, "fav_empty"),
                                  call.message.chat.id, call.message.message_id)
        except Exception:
            pass


@bot.callback_query_handler(func=lambda c: c.data.startswith("ad|"))
def cb_alert_del(call: types.CallbackQuery):
    uid = call.from_user.id

    try:
        idx = int(call.data.split("|")[1])
        user_alerts[uid].pop(idx)
    except (IndexError, ValueError):
        pass

    bot.answer_callback_query(call.id, t(uid, "alr_del"))

    if user_alerts[uid]:
        try:
            bot.edit_message_reply_markup(
                call.message.chat.id, call.message.message_id, reply_markup=alert_kb(uid))
        except Exception:
            pass
    else:
        try:
            bot.edit_message_text(t(uid, "alr_empty"),
                                  call.message.chat.id, call.message.message_id)
        except Exception:
            pass


@bot.callback_query_handler(func=lambda c: c.data.startswith("hp|"))
def cb_hp(call: types.CallbackQuery):
    uid = call.from_user.id
    parts = call.data.split("|")
    days = int(parts[1])
    coin = parts[2]
    cg_id = COINS.get(coin)

    if not cg_id:
        bot.answer_callback_query(call.id, t(uid, "bad_coin"))
        return

    bot.answer_callback_query(call.id, "Загружаю...")
    prices = _fetch_history(cg_id, days)

    if not prices:
        send_and_track(uid, call.message.chat.id, t(uid, "hp_err"))
        return

    cur = currency(uid)
    mn = min(p for _, p in prices)
    mx = max(p for _, p in prices)
    first = prices[0][1];
    last_p = prices[-1][1]
    pct = ((last_p - first) / first * 100) if first else 0
    sign = "+" if pct >= 0 else ""

    # Конвертируем в валюту пользователя
    if cur != "USD":
        rate = rates["USD"][cur] if "USD" in rates and cur in rates["USD"] else 1
        mn = mn * rate
        mx = mx * rate
        last_p = last_p * rate

    chart = _build_chart(prices, cur)

    send_and_track(uid, call.message.chat.id,
                   t(uid, "hp_hdr", coin=coin, ts=ts()) +
                   chart +
                   t(uid, "hp_stat", mn=fmt(mn), mx=fmt(mx), ch=f"{sign}{pct:.2f}", now=fmt(last_p)))


@bot.callback_query_handler(func=lambda c: c.data == "noop")
def cb_noop(call: types.CallbackQuery):
    bot.answer_callback_query(call.id)


# ─────────────────────────────────────────
#  INLINE
# ─────────────────────────────────────────
@bot.inline_handler(func=lambda q: True)
def inline_handler(query: types.InlineQuery):
    text = query.query.strip()
    if not text or not rates:
        bot.answer_inline_query(query.id, [
            types.InlineQueryResultArticle(
                id="help",
                title="Convert Bot — введите запрос",
                description="Пример: 100 usd ton  |  0.5 btc eth",
                input_message_content=types.InputTextMessageContent(
                    "@convertconvertbot 100 usd ton"))
        ], cache_time=1)
        return

    amount, frm, to = parse_query(text)
    if amount is None:
        bot.answer_inline_query(query.id, [], cache_time=1)
        return

    results = []
    if to:
        r = convert(amount, frm, to)
        if r is not None:
            body = f"{fmt(amount)} {frm} = {fmt(r)} {to}  (курс {ts()})"
            results.append(types.InlineQueryResultArticle(
                id=hashlib.md5(body.encode()).hexdigest(),
                title=f"{fmt(amount)} {frm} = {fmt(r)} {to}",
                description=f"Курс на {ts()}",
                input_message_content=types.InputTextMessageContent(body)))
    else:
        for c in [x for x in ["TON", "BTC", "ETH", "BNB", "SOL", "USDT", "USD", "EUR", "RUB"] if x != frm][:8]:
            r = convert(amount, frm, c)
            if r is None:
                continue
            body = f"{fmt(amount)} {frm} = {fmt(r)} {c}  (курс {ts()})"
            results.append(types.InlineQueryResultArticle(
                id=hashlib.md5(f"{c}{body}".encode()).hexdigest(),
                title=f"{fmt(amount)} {frm} = {fmt(r)} {c}",
                description=f"Курс на {ts()}",
                input_message_content=types.InputTextMessageContent(body)))

    bot.answer_inline_query(query.id, results, cache_time=60)


# ─────────────────────────────────────────
#  ГЛАВНЫЙ ОБРАБОТЧИК ТЕКСТА
# ─────────────────────────────────────────
ALL_BUTTONS: dict = {}  # текст кнопки -> ключ


def _build_button_map():
    for lg in T.values():
        for key in ["b_conv", "b_rates", "b_top", "b_24h", "b_cmp", "b_fav",
                    "b_port", "b_alr", "b_hp", "b_news", "b_calc", "b_curr"]:
            if key in lg:
                ALL_BUTTONS[lg[key]] = key


_build_button_map()


@bot.message_handler(content_types=["text"])
def handle_text(msg: types.Message):
    uid = msg.from_user.id
    text = msg.text or ""
    cid = msg.chat.id
    register(uid, msg.from_user.full_name or "")

    # FSM
    state = user_state.get(uid)

    if state == "conv":
        user_state.pop(uid, None)
        process_convert(cid, uid, text)
        return

    if state == "cmp":
        user_state.pop(uid, None)
        coins = [tok for tok in text.upper().split() if tok in COINS]
        if len(coins) < 2:
            send_and_track(uid, cid, t(uid, "cmp_bad"), reply_markup=main_kb(uid))
        else:
            send_compare(cid, uid, coins[0], coins[1])
        return

    if state == "calc":
        user_state.pop(uid, None)
        process_profit(cid, uid, text)
        return

    if state == "hp":
        user_state.pop(uid, None)
        coin = text.strip().upper()
        if coin not in COINS or coin in FIAT:
            send_and_track(uid, cid, t(uid, "bad_coin"), reply_markup=main_kb(uid))
        else:
            send_and_track(uid, cid, t(uid, "hp_choose"), reply_markup=hp_kb(coin))
        return

    # Кнопки меню
    key = ALL_BUTTONS.get(text)

    if key == "b_conv":
        user_state[uid] = "conv"
        delete_previous(uid, cid)
        bot.send_message(cid, t(uid, "ask_conv"), reply_markup=types.ReplyKeyboardRemove())

    elif key == "b_rates":
        send_rates(cid, uid)

    elif key == "b_top":
        send_top(cid, uid)

    elif key == "b_24h":
        send_24h(cid, uid)

    elif key == "b_cmp":
        user_state[uid] = "cmp"
        delete_previous(uid, cid)
        bot.send_message(cid, t(uid, "ask_cmp"), reply_markup=types.ReplyKeyboardRemove())

    elif key == "b_fav":
        send_favorites(cid, uid)

    elif key == "b_port":
        send_portfolio(cid, uid)

    elif key == "b_alr":
        send_alerts(cid, uid)

    elif key == "b_hp":
        user_state[uid] = "hp"
        delete_previous(uid, cid)
        bot.send_message(cid, t(uid, "ask_hp"), reply_markup=types.ReplyKeyboardRemove())

    elif key == "b_news":
        send_news_channel_link(cid, uid)

    elif key == "b_calc":
        user_state[uid] = "calc"
        delete_previous(uid, cid)
        bot.send_message(cid, t(uid, "ask_calc"), reply_markup=types.ReplyKeyboardRemove())

    elif key == "b_curr":
        delete_previous(uid, cid)
        bot.send_message(cid, t(uid, "curr_choose"), reply_markup=currency_kb(uid))

    else:
        # Прямой ввод конвертации
        amount, _, _ = parse_query(text)
        if amount is not None:
            process_convert(cid, uid, text)


# ─────────────────────────────────────────
#  ЗАПУСК
# ─────────────────────────────────────────
if __name__ == "__main__":
    log.info("Convert Bot v7.0 запускается...")
    _fetch_rates()  # сначала грузим курсы синхронно
    threading.Thread(target=_rates_loop, daemon=True).start()
    threading.Thread(target=_alert_loop, daemon=True).start()
    log.info("Готов. Polling...")
    bot.infinity_polling(timeout=30, long_polling_timeout=30)