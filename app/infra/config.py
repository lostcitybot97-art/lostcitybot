import os

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
MERCADOPAGO_ACCESS_TOKEN = os.getenv("MERCADOPAGO_ACCESS_TOKEN")

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN não definido")

if not MERCADOPAGO_ACCESS_TOKEN:
    raise RuntimeError("MERCADOPAGO_ACCESS_TOKEN não definido")
