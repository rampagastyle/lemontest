import qrcode
from io import BytesIO
import uuid

# Префикс deep-link параметра: https://t.me/<бот>?start=t_<код билета>
TICKET_PREFIX = "t_"


def build_ticket_link(bot_username: str, code: str) -> str:
    """Ссылка, которую кодирует QR: открывает бота и передаёт ему код билета."""
    return f"https://t.me/{bot_username}?start={TICKET_PREFIX}{code}"


def generate_qr_code(data: str) -> BytesIO:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    bio = BytesIO()
    bio.name = 'qr_code.png'
    img.save(bio, 'PNG')
    bio.seek(0)
    return bio


async def make_ticket_qr(bot, code: str) -> BytesIO:
    """QR-картинка билета: внутри ссылка на бота с кодом билета."""
    me = await bot.me()
    return generate_qr_code(build_ticket_link(me.username, code))


def generate_unique_ticket_code() -> str:
    return str(uuid.uuid4())
