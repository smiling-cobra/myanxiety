import os
import logging

from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

# httpx logs every request URL at INFO, and Telegram carries the bot token in
# the URL path — so at the root INFO level each getUpdates poll writes the token
# to the logs a few times a minute. Nothing below WARNING from httpx is worth
# that. python-telegram-bot v13 used urllib3 and never logged this.
logging.getLogger('httpx').setLevel(logging.WARNING)

load_dotenv()

from config import require_config

# Before the imports below: they construct services, and a missing secret would
# otherwise surface as a traceback from whichever one reads it first.
require_config()

from telegram.ext import Application
from bot.handlers import commands, errors, journal
from bot.persistence import MongoPersistence
from db.db import get_db
from services.scheduler_service import SchedulerService

telegram_bot_token = os.environ.get('TELEGRAM_TOKEN')


def main() -> None:
    get_db()  # fail fast on a missing MONGODB_URI, not on the first check-in

    application = (
        Application.builder()
        .token(telegram_bot_token)
        .persistence(MongoPersistence())
        .build()
    )

    logging.info('Application start...')

    commands.register(application)
    journal.register(application)
    errors.register(application)

    SchedulerService().start(application.job_queue)

    logging.info('Polling for updates...')

    # Replaces start_polling() + idle(): run_polling owns the event loop and
    # handles initialisation and graceful shutdown itself.
    application.run_polling()


if __name__ == '__main__':
    main()
