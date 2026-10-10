from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.fsm.context import FSMContext

from database import db
from utils import create_payment, generate_unique_ticket_code, generate_qr_code, check_payment_status
from keyboards import payment_keyboard

router = Router()


@router.callback_query(F.data.startswith("buy_"))
async def process_buy_ticket(callback: CallbackQuery, state: FSMContext):
    event_id = int(callback.data.split("_")[1])
    event = await db.get_event(event_id)

    if not event:
        await callback.answer("❌ Мероприятие не найдено", show_alert=True)
        return

    if event['available_tickets'] <= 0:
        await callback.answer("❌ Билеты закончились", show_alert=True)
        return

    try:
        payment = await create_payment(
            amount=event['price'],
            description=f"Билет на {event['name']}"
        )

        await state.update_data(
            event_id=event_id,
            payment_id=payment['id']
        )

        text = f"""
🎫 Оформление билета

Мероприятие: {event['name']}
Цена: {event['price']}₽

Нажмите кнопку ниже для оплаты.
После оплаты билет придет автоматически.
        """

        await callback.message.answer(
            text,
            reply_markup=payment_keyboard(payment['confirmation_url'])
        )
        await callback.answer()

    except Exception as e:
        await callback.answer("❌ Ошибка создания платежа", show_alert=True)
        print(f"Payment error: {e}")


@router.message(F.text.startswith("/check_payment_"))
async def manual_check_payment(message: Message, state: FSMContext):
    try:
        payment_id = message.text.split("_")[2]
        status = await check_payment_status(payment_id)

        if status == "succeeded":
            data = await state.get_data()
            event_id = data.get('event_id')

            if not event_id:
                await message.answer("❌ Не найдена информация о заказе")
                return

            qr_code = generate_unique_ticket_code()

            ticket_id = await db.create_ticket(
                event_id=event_id,
                user_id=message.from_user.id,
                username=message.from_user.username or "Unknown",
                qr_code=qr_code,
                payment_id=payment_id
            )

            event = await db.get_event(event_id)
            qr_image = generate_qr_code(qr_code)

            text = f"""
✅ Билет успешно куплен!

🎉 {event['name']}
📅 {event['date'].strftime("%d.%m.%Y %H:%M")}
📍 {event['location']}

Ваш билет:
            """

            photo = BufferedInputFile(qr_image.read(), filename="ticket_qr.png")
            await message.answer_photo(photo=photo, caption=text)

            await state.clear()
        else:
            await message.answer(f"⏳ Статус оплаты: {status}")

    except Exception as e:
        await message.answer("❌ Ошибка проверки платежа")
        print(f"Check payment error: {e}")


@router.callback_query(F.data == "cancel_payment")
async def cancel_payment(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("❌ Оплата отменена")
    await callback.answer()
