import mongomock
import pytest

import db.db as db_module


@pytest.fixture(autouse=True)
def mock_db(monkeypatch):
    """Replace the MongoDB connection with an in-memory mongomock instance.

    Applied automatically to every test so no test ever touches a real database.
    The fixture resets _db to None after each test so the next test starts clean.
    """
    client = mongomock.MongoClient()
    db = client['anxiety_journal']
    monkeypatch.setattr(db_module, '_db', db)
    yield db
    monkeypatch.setattr(db_module, '_db', None)
