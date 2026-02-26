import os


# =========================
# TELEGRAM
# =========================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

WEBHOOK_URL = os.getenv("WEBHOOK_URL")

OWNER_ID = os.getenv("OWNER_ID")
ADMIN_USER_IDS = [
    int(x) for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x
]

GRUPO_ID = os.getenv("GRUPO_ID")


# =========================
# MERCADO PAGO
# =========================

MP_ACCESS_TOKEN = os.getenv("MERCADOPAGO_ACCESS_TOKEN")

if not MP_ACCESS_TOKEN:
    raise RuntimeError("MERCADOPAGO_ACCESS_TOKEN não definido no ambiente")

