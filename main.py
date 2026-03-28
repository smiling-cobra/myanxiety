import os
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

from telegram.ext import Updater
from bot.handlers import commands, journal
from db.db import get_db
from services.scheduler_service import SchedulerService

telegram_bot_token = os.environ.get('TELEGRAM_TOKEN')


def main() -> None:
    get_db()  # initialise MongoDB before worker threads start

    updater = Updater(telegram_bot_token, use_context=True)
    dispatcher = updater.dispatcher

    logging.info('Application start...')

    commands.register(dispatcher)
    journal.register(dispatcher)

    SchedulerService().start(updater.job_queue)

    # Start polling the bot for updates
    logging.info('Pooooolling...')

    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main()
