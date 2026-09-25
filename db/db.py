import os
from pymongo import MongoClient
from pymongo.database import Database
from dotenv import load_dotenv

load_dotenv()

_client: MongoClient = None
_db: Database = None

# Every Mongo call now runs in a worker thread handed off from the event loop.
# pymongo's 30s default would pin one of those threads for half a minute and
# leave the user staring at nothing before the error arrives.
_SERVER_SELECTION_TIMEOUT_MS = 5000


def get_db() -> Database:
    global _client, _db

    if _db is None:
        mongo_uri = os.environ.get('MONGODB_URI')

        if not mongo_uri:
            raise ValueError('MONGODB_URI is not set in environment variables')

        _client = MongoClient(mongo_uri, serverSelectionTimeoutMS=_SERVER_SELECTION_TIMEOUT_MS)
        _db = _client['anxiety_journal']

    return _db


def get_collection(name: str):
    return get_db()[name]


# Collection accessors
def users_collection():
    return get_collection('users')


def entries_collection():
    return get_collection('entries')


def streaks_collection():
    return get_collection('streaks')


def notifications_collection():
    return get_collection('notifications')


# Product analytics. Behavioural events and per-user LLM spend counters — never
# entry text (see services/analytics_service.py). Both are user-linked, so both
# belong in the /delete fan-out when that ships.
def events_collection():
    return get_collection('events')


def usage_collection():
    return get_collection('usage')


# Telegram Stars payments for Plus: charge ids, amounts and dates. User-linked,
# so it is in the /delete fan-out.
def payments_collection():
    return get_collection('payments')


# python-telegram-bot persistence. Framework state, not domain data — kept in
# their own collections so a /delete fan-out can see them for what they are.
def conversations_collection():
    return get_collection('ptb_conversations')


def user_data_collection():
    return get_collection('ptb_user_data')
