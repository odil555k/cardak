import asyncio
import hashlib
import logging
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx

from telethon import TelegramClient, events
from telethon.sessions import StringSession


# ============================================================
# НАСТРОЙКИ
# ============================================================

API_ID = int(
    os.environ.get(
        "CARDXABAR_API_ID",
        "32415036",
    )
)

API_HASH = os.environ.get(
    "CARDXABAR_API_HASH",
    "b07d9a03d2aee0e24196a816b4d653e9",
).strip()

CARDXABAR_ID = 915326936

CARDXABAR_API_KEY = os.environ.get(
    "CARDXABAR_API_KEY",
    "a2e2f5641efd5cf857aedbde1358638fce70ec8f5a24ece8",
).strip()

STARPAY_API_URL = os.environ.get(
    "STARPAY_API_URL",
    "/cardxabar",
).strip()


# ============================================================
# TELETHON SESSION
# ============================================================

# На Render сюда будет передана длинная StringSession.
TELETHON_SESSION = os.environ.get(
    "TELETHON_SESSION",
    "",
).strip()

# Локальное имя файла сессии.
# Он используется только если TELETHON_SESSION не задана.
SESSION_NAME = "cardxabar_device"


# ============================================================
# ЛОГИ
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger("cardxabar")


# ============================================================
# ПРОВЕРКА НАСТРОЕК
# ============================================================

def check_settings():
    print()
    print("=" * 60)
    print("             ПРОВЕРКА НАСТРОЕК")
    print("=" * 60)

    print(f"📡 CardXabar ID: {CARDXABAR_ID}")
    print(f"🌐 StarPay API: {STARPAY_API_URL}")
    print(
        f"🔑 API KEY задан: "
        f"{bool(CARDXABAR_API_KEY)}"
    )
    print(
        f"🔐 API HASH задан: "
        f"{bool(API_HASH)}"
    )
    print(
        f"📱 TELETHON_SESSION задана: "
        f"{bool(TELETHON_SESSION)}"
    )

    if TELETHON_SESSION:
        print(
            "📱 Режим: StringSession "
            "(Render)"
        )
    else:
        print(
            "📁 Режим: локальный файл "
            f"{SESSION_NAME}.session"
        )

    print("=" * 60)
    print()


# ============================================================
# HTTP SERVER ДЛЯ RENDER
# ============================================================

class HealthHandler(BaseHTTPRequestHandler):

    def send_json(self, status_code, data):
        import json

        body = json.dumps(
            data,
            ensure_ascii=False,
        ).encode("utf-8")

        self.send_response(status_code)

        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8",
        )

        self.send_header(
            "Content-Length",
            str(len(body)),
        )

        self.end_headers()

        self.wfile.write(body)

    def do_GET(self):

        if self.path == "/":
            self.send_json(
                200,
                {
                    "status": "ok",
                    "service": "cardxabar-client",
                },
            )
            return

        if self.path == "/health":
            self.send_json(
                200,
                {
                    "status": "ok",
                },
            )
            return

        self.send_json(
            404,
            {
                "status": "not_found",
            },
        )

    def do_HEAD(self):

        if self.path in ("/", "/health"):
            self.send_response(200)
            self.end_headers()
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        return


def start_web_server():

    port = int(
        os.environ.get(
            "PORT",
            "10000",
        )
    )

    server = ThreadingHTTPServer(
        ("0.0.0.0", port),
        HealthHandler,
    )

    print(
        f"🌐 HTTP сервер запущен "
        f"на порту {port}"
    )

    server.serve_forever()


# ============================================================
# ОТПРАВКА ПЛАТЕЖА В STARPAY
# ============================================================

async def send_payment_to_starpay(
    payment_amount,
    fingerprint,
    raw_text,
):

    if not CARDXABAR_API_KEY:
        print(
            "❌ CARDXABAR_API_KEY не задан."
        )
        return None

    payload = {
        "payment_amount": payment_amount,
        "fingerprint": fingerprint,
        "raw_text": raw_text,
    }

    headers = {
        "X-CardXabar-Key": CARDXABAR_API_KEY,
        "Content-Type": "application/json",
    }

    print()
    print(
        "📡 Отправляю перевод "
        "на StarPay..."
    )

    print(
        f"💰 Сумма: "
        f"{payment_amount:,} UZS"
    )

    try:

        timeout = httpx.Timeout(
            connect=10.0,
            read=30.0,
            write=30.0,
            pool=30.0,
        )

        async with httpx.AsyncClient(
            timeout=timeout
        ) as http_client:

            response = await http_client.post(
                STARPAY_API_URL,
                json=payload,
                headers=headers,
            )

        print(
            f"🌐 HTTP: "
            f"{response.status_code}"
        )

        try:
            result = response.json()

        except Exception:

            print(
                "❌ StarPay вернул "
                "не JSON:"
            )

            print(response.text)

            return None

        print(
            f"📥 Ответ StarPay: "
            f"{result}"
        )

        if not (
            200
            <= response.status_code
            < 300
        ):
            return None

        return result

    except httpx.TimeoutException:

        print(
            "❌ StarPay не ответил "
            "вовремя."
        )

        return None

    except Exception as e:

        print(
            f"❌ Ошибка соединения "
            f"со StarPay: {e}"
        )

        return None


# ============================================================
# ОБРАБОТКА СООБЩЕНИЙ
# ============================================================

async def new_cardxabar_message(event):

    try:

        text = event.raw_text or ""

        print()
        print("=" * 60)
        print("📨 НОВОЕ СООБЩЕНИЕ")
        print("=" * 60)
        print(text)
        print("=" * 60)

        # ----------------------------------------------------
        # Только входящий перевод
        # ----------------------------------------------------

        if "🟢 Perevod na kartu" not in text:

            print(
                "⏭ Это не входящий "
                "перевод. Пропуск."
            )

            return

        # ----------------------------------------------------
        # Ищем сумму
        #
        # Например:
        # ➕ 1 000.00 UZS
        # ----------------------------------------------------

        match = re.search(
            r"➕\s*([\d\s]+(?:[.,]\d+)?)\s*UZS",
            text,
            re.IGNORECASE,
        )

        if not match:

            print(
                "❌ Не удалось найти "
                "сумму перевода."
            )

            return

        amount_text = match.group(1)

        amount_text = (
            amount_text
            .replace(" ", "")
            .replace(",", ".")
        )

        try:

            amount_float = float(
                amount_text
            )

            payment_amount = int(
                round(amount_float)
            )

        except ValueError:

            print(
                f"❌ Неверная сумма: "
                f"{amount_text}"
            )

            return

        print(
            f"✅ Входящий перевод: "
            f"{payment_amount:,} UZS"
        )

        # ----------------------------------------------------
        # Уникальный fingerprint
        # ----------------------------------------------------

        fingerprint_source = (
            f"{event.chat_id}:"
            f"{event.id}:"
            f"{text}"
        )

        fingerprint = hashlib.sha256(
            fingerprint_source.encode(
                "utf-8"
            )
        ).hexdigest()

        print(
            f"🔐 Fingerprint: "
            f"{fingerprint[:16]}..."
        )

        # ----------------------------------------------------
        # Передаём перевод в StarPay
        # ----------------------------------------------------

        result = await send_payment_to_starpay(
            payment_amount=payment_amount,
            fingerprint=fingerprint,
            raw_text=text,
        )

        if result is None:

            print(
                "❌ Не удалось обработать "
                "перевод через StarPay."
            )

            return

        # ----------------------------------------------------
        # Ответ
        # ----------------------------------------------------

        if result.get(
            "duplicate",
            False,
        ):

            print(
                "⚠️ Этот перевод уже "
                "был обработан."
            )

            return

        if result.get(
            "found",
            False,
        ):

            if result.get(
                "credited",
                False,
            ):

                print()
                print(
                    "🎉 БАЛАНС ПОПОЛНЕН!"
                )

                print(
                    f"👤 User ID: "
                    f"{result.get('user_id')}"
                )

                print(
                    f"💰 Зачислено: "
                    f"{result.get('requested_amount')}"
                )

                return

            if result.get(
                "dry_run",
                False,
            ):

                print()
                print(
                    "🧪 DRY RUN: "
                    "платёж найден."
                )

                print(
                    f"👤 User ID: "
                    f"{result.get('user_id')}"
                )

                return

        print(
            "ℹ️ Подходящая заявка "
            "на этот перевод не найдена."
        )

    except Exception as e:

        logger.exception(
            f"Ошибка обработки "
            f"сообщения: {e}"
        )


# ============================================================
# СОЗДАНИЕ TELETHON CLIENT
# ============================================================

def create_client():

    # --------------------------------------------------------
    # Render:
    # используем StringSession из Environment Variables
    # --------------------------------------------------------

    if TELETHON_SESSION:

        print(
            "📱 Используется "
            "TELETHON_SESSION из Render."
        )

        session = StringSession(
            TELETHON_SESSION
        )

    # --------------------------------------------------------
    # Локальный PyCharm:
    # используем cardxabar_device.session
    # --------------------------------------------------------

    else:

        print(
            "📁 Используется локальная "
            f"сессия {SESSION_NAME}.session"
        )

        session = SESSION_NAME

    client = TelegramClient(
        session,
        API_ID,
        API_HASH,
        device_model="Redmi 10",
        system_version="Android",
        app_version="1.0",
    )

    client.add_event_handler(
        new_cardxabar_message,
        events.NewMessage(
            from_users=CARDXABAR_ID
        ),
    )

    return client


# ============================================================
# MAIN
# ============================================================

async def main():

    check_settings()

    # --------------------------------------------------------
    # Проверяем обязательные настройки
    # --------------------------------------------------------

    if not API_HASH:

        print(
            "❌ CARDXABAR_API_HASH "
            "не задан."
        )

        return

    if not CARDXABAR_API_KEY:

        print(
            "❌ CARDXABAR_API_KEY "
            "не задан."
        )

        return

    if not STARPAY_API_URL:

        print(
            "❌ STARPAY_API_URL "
            "не задан."
        )

        return

    # --------------------------------------------------------
    # Запускаем HTTP-сервер
    # --------------------------------------------------------

    web_thread = threading.Thread(
        target=start_web_server,
        daemon=True,
    )

    web_thread.start()

    # --------------------------------------------------------
    # Создаём Telegram Client
    # --------------------------------------------------------

    client = create_client()

    print()
    print(
        "⏳ Подключаемся к Telegram..."
    )

    try:

        await client.start()

    except Exception as e:

        print()
        print(
            "❌ Не удалось подключиться "
            "к Telegram."
        )

        print(
            f"Ошибка: {e}"
        )

        return

    print()
    print(
        "✅ Telegram подключён!"
    )

    # --------------------------------------------------------
    # Информация об аккаунте
    # --------------------------------------------------------

    try:

        me = await client.get_me()

        if me:

            username = (
                f"@{me.username}"
                if me.username
                else "без username"
            )

            print(
                f"👤 Аккаунт: "
                f"{me.first_name or ''} "
                f"{username}"
            )

    except Exception:
        pass

    print()
    print(
        "✅ Telegram-сессия активна."
    )

    print(
        "⏳ Ожидаю новые сообщения..."
    )

    print("=" * 60)

    # --------------------------------------------------------
    # Работаем постоянно
    # --------------------------------------------------------

    try:

        await client.run_until_disconnected()

    finally:

        await client.disconnect()


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(main())

    except KeyboardInterrupt:

        print()
        print(
            "🛑 Программа остановлена."
        )