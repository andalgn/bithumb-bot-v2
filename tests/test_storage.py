"""StateStorage 테스트."""

import pytest

from app.storage import StateStorage


@pytest.fixture
def storage(tmp_path) -> StateStorage:
    """테스트용 StateStorage."""
    return StateStorage(path=str(tmp_path / "state.json"))


class TestStateStorage:
    """상태 영속화 테스트."""

    def test_set_get(self, storage: StateStorage) -> None:
        """값 설정 및 조회."""
        storage.set("key1", "value1")
        assert storage.get("key1") == "value1"

    def test_save_load(self, tmp_path) -> None:
        """저장 및 복원."""
        path = str(tmp_path / "state.json")
        s1 = StateStorage(path=path)
        s1.set("counter", 42)
        s1.set("positions", {"BTC": {"qty": 0.001}})
        s1.save()

        s2 = StateStorage(path=path)
        assert s2.get("counter") == 42
        assert s2.get("positions")["BTC"]["qty"] == 0.001

    def test_default_value(self, storage: StateStorage) -> None:
        """존재하지 않는 키 → 기본값."""
        assert storage.get("missing", "default") == "default"

    def test_update(self, storage: StateStorage) -> None:
        """일괄 갱신."""
        storage.update({"a": 1, "b": 2})
        assert storage.get("a") == 1
        assert storage.get("b") == 2
