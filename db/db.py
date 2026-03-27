import os
from pymongo import MongoClient
from pymongo.database import Database
from dotenv import load_dotenv

load_dotenv()

_client: MongoClient = None
_db: Database = None


def get_db() -> Database:
    global _client, _db

    if _db is None:
        mongo_uri = os.environ.get('MONGODB_URI')

        if not mongo_uri:
            raise ValueError('MONGODB_URI is not set in environment variables')

        _client = MongoClient(mongo_uri)
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