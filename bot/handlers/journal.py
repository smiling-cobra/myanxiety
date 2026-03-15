import logging

from bot.keyboards import get_lobby_keyboard, get_option_keyboard
from messages.strings import WELCOME_MESSAGE_CONCISE
from telegram import Update, ReplyKeyboardRemove
from telegram.ext import (
    CommandHandler,
    MessageHandler,
    Filters,
    CallbackContext,
    ConversationHandler
)
from services import LlmService
from messages.strings import (
    create_farewell_message
)

DESTINATION, LOBBY = range(2)

llm_service = LlmService()


class UserDialogueHelper:
    def __init__(self, dispatcher):
        self.dispatcher = dispatcher

    def handle_initial_user_input(
        self,
        update: Update,
        context: CallbackContext
    ):
        logging.info(f'Entire message ===>: {update.message}')

        # Extract city name from user input
        user_input = update.message.text
        user_name = update.message.chat.first_name

        logging.info('info', f'Handling user input: {user_name} {user_input}', )
        
        # update.message.reply_text('Hello, people', reply_markup=get_lobby_keyboard())

        return LOBBY

    def handle_lobby_choice(self, update: Update, context: CallbackContext):
        user_choice = update.message.text
        user_name = update.message.chat.first_name

        pass
    
    def start(self, update: Update, context: CallbackContext):
        user_name = update.message.chat.first_name
        welcome_message = WELCOME_MESSAGE_CONCISE.format(user_name)
        update.message.reply_text(welcome_message)
        return DESTINATION

    def cancel(self, update: Update, context: CallbackContext):
        user_name = update.message.chat.first_name

        update.message.reply_text(
            create_farewell_message(user_name),
            reply_markup=ReplyKeyboardRemove()
        )

        return ConversationHandler.END

    def setup(self):
        # Create the ConversationHandler to handle
        # the onboarding process and lobby choices

        conversation_handler = ConversationHandler(
            entry_points=[CommandHandler('start', self.start)],
            states={
                DESTINATION: [
                    MessageHandler(
                        Filters.text & ~Filters.command,
                        self.handle_initial_user_input
                    )
                ],
                LOBBY: [
                    MessageHandler(
                        Filters.text & ~Filters.command,
                        self.handle_lobby_choice
                    )
                ]
            },
            fallbacks=[CommandHandler('cancel', self.cancel)]
        )

        # Add the ConversationHandler to the dispatcher
        self.dispatcher.add_handler(conversation_handler)
