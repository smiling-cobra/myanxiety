from telegram import ReplyKeyboardRemove, Update
from telegram.ext import CallbackContext, CommandHandler, ConversationHandler

from messages.strings import create_farewell_message

WELCOME_MESSAGE_CONCISE = 'Guten Tag, dear {} and his anxiety!'

def start(update: Update, context: CallbackContext):
    user_name = update.message.chat.first_name
    update.message.reply_text(WELCOME_MESSAGE_CONCISE.format(user_name))

def cancel(update: Update, context: CallbackContext):
    update.message.reply_text(
        create_farewell_message(update.message.chat.first_name),
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

def register(dispatcher):
    dispatcher.add_handler(CommandHandler('start', start))
    dispatcher.add_handler(CommandHandler('cancel', cancel))