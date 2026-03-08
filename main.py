
import os
import logging
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext
from handlers import GroupMessageHandler, UserDialogueHelper
from messages import HELP_WELCOME_MESSAGE
from services import LoggingService

telegram_bot_token = os.environ.get('TELEGRAM_TOKEN')
geocoding_api_url = os.environ.get('GEOCODING_API_URL')
google_map_api_key = os.environ.get('GOOGLE_MAP_API_KEY')


def error(update: Update, context: CallbackContext):
    print(f'Update {update} caused error {context.error}')
    pass


def help(update: Update):
    update.message.reply_text(HELP_WELCOME_MESSAGE)
    pass


def main() -> None:
    # Ensure logging is configured for Docker/terminal visibility
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler()]
    )

    updater = Updater(telegram_bot_token, use_context=True)
    dispatcher = updater.dispatcher

    logger = LoggingService()
    logger.log('info', 'Application start')

    conversation_handler = UserDialogueHelper(
        dispatcher,
        logger
    )
    conversation_handler.setup()

    group_message_handler = GroupMessageHandler(dispatcher)
    group_message_handler.setup()

    dispatcher.add_handler(CommandHandler('help', help))

    # Start polling the bot for updates
    logger.log('info', 'Polling...')
    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main()
