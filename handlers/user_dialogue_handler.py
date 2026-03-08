import os
from common import get_lobby_keyboard, get_city_name, get_option_keyboard
from messages import WELCOME_MESSAGE_CONCISE
from telegram import Update, ReplyKeyboardRemove
from commands import (
    Places,
    BackCommand,
    HelpCommand,
)
from telegram.ext import (
    CommandHandler,
    MessageHandler,
    Filters,
    CallbackContext,
    ConversationHandler
)
from services import LlmService, LoggingService
from messages import (
    NO_CITY_FOUND_MESSAGE,
    DEFAULT_USER_NAME,
    create_wrong_input_message,
    create_farewell_message
)

DESTINATION, LOBBY = range(2)

llm_service = LlmService()
logger = LoggingService()

PLACES = '🗽 Places'
HELP = '❓ Help'
BACK = '🔙 Back'

user_choice_to_command = {
    PLACES: Places(
        get_city_name,
        get_option_keyboard,
        logger
    ),
    HELP: HelpCommand(),
    BACK: BackCommand()
}


class UserDialogueHelper:
    def __init__(self, dispatcher, logger):
        self.dispatcher = dispatcher
        self.logger = logger

    def handle_initial_user_input(
        self,
        update: Update,
        context: CallbackContext
    ):
        self.logger.log('info', f'Entire message ===>: {update.message}')

        # Extract city name from user input
        user_input = update.message.text
        user_name = update.message.chat.first_name or DEFAULT_USER_NAME

        city_data = self.city_data_service.fetch_city_data(user_input)

        self.logger.log('info', f'City data ===>: {city_data}')

        if not city_data:
            update.message.reply_text(
                NO_CITY_FOUND_MESSAGE.format(user_name),
                reply_markup=ReplyKeyboardRemove()
            )
            return ConversationHandler.END

        # Save city data in context for later use in the conversation handlers
        # This allows us to avoid redundant API calls when the user selects different options in the lobby
        # 2026-03-08: Consider using a more robust state management solution, such as a database or in-memory store.
        context.user_data['city_data'] = city_data

        self.logger.log('info', f'City data saved to context: {context.user_data}')
                
        try:
            city_name = city_data[0].get('formatted_address')
        except (IndexError, KeyError) as e:
            self.logger.log('error', f'Error extracting city name: {e}')
            city_name = user_input  # Fallback to user input if formatted address is not available
        
        update.message.reply_text(
            self.create_initial_greeting_message(user_name, city_name),
            reply_markup=get_lobby_keyboard()
        )

        return LOBBY
    
    def create_initial_greeting_message(self, user_name, city_name) -> str:
        return f"You're heading to {city_name}, {user_name}! Let's see what I can do for you."

    def handle_lobby_choice(self, update: Update, context: CallbackContext):
        user_choice = update.message.text
        user_name = update.message.chat.first_name or DEFAULT_USER_NAME

        command = user_choice_to_command.get(user_choice)

        self.logger.log('info', f'User choice: {user_choice}, Mapped command: {command}')
        
        if command:
            command.execute(update, context)
        else:
            # Need to handle this more gracefully.
            update.message.reply_text(create_wrong_input_message(user_name))

    def start(self, update: Update, context: CallbackContext):
        user_name = update.message.chat.first_name or DEFAULT_USER_NAME
        welcome_message = WELCOME_MESSAGE_CONCISE.format(user_name)
        update.message.reply_text(welcome_message)
        return DESTINATION

    def cancel(self, update: Update, context: CallbackContext):
        user_name = update.message.chat.first_name or DEFAULT_USER_NAME

        update.message.reply_text(
            create_farewell_message(user_name),
            reply_markup=ReplyKeyboardRemove()
        )

        return ConversationHandler.END

    def setup(self):
        # Create the ConversationHandler to handle
        # the onboarding process and lobby choices

        conv_handler = ConversationHandler(
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
        self.dispatcher.add_handler(conv_handler)
