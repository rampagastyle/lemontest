from yookassa import Configuration, Payment
import uuid
import config

Configuration.account_id = config.YOOKASSA_SHOP_ID
Configuration.secret_key = config.YOOKASSA_SECRET_KEY


async def create_payment(amount: int, description: str, return_url: str = None) -> dict:
    idempotence_key = str(uuid.uuid4())

    payment = Payment.create({
        "amount": {
            "value": f"{amount}.00",
            "currency": "RUB"
        },
        "confirmation": {
            "type": "redirect",
            "return_url": return_url or "https://t.me/your_bot"
        },
        "capture": True,
        "description": description
    }, idempotence_key)

    return {
        "id": payment.id,
        "status": payment.status,
        "confirmation_url": payment.confirmation.confirmation_url
    }


async def check_payment_status(payment_id: str) -> str:
    payment = Payment.find_one(payment_id)
    return payment.status
