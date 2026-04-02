import pytest

from app.state_store import StateStore


@pytest.fixture
def store(tmp_path):
    return StateStore(db_path=str(tmp_path / "test.db"))


def test_set_and_get(store):
    store.set("positions", {"BTC": {"qty": 1.0}})
    val = store.get("positions")
    assert val == {"BTC": {"qty": 1.0}}


def test_get_missing_returns_default(store):
    assert store.get("nonexistent") is None
    assert store.get("nonexistent", default={}) == {}


def test_update_existing_key(store):
    store.set("pool", {"core": 1000})
    store.set("pool", {"core": 2000})
    assert store.get("pool") == {"core": 2000}


def test_migration_complete_flag(store):
    assert store.is_migration_complete() is False
    store.set_migration_complete()
    assert store.is_migration_complete() is True


def test_all_keys(store):
    store.set("a", 1)
    store.set("b", 2)
    keys = store.all_keys()
    assert set(keys) >= {"a", "b"}
