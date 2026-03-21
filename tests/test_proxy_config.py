"""프록시 설정 로딩 테스트."""
from app.config import load_config


def test_load_config_has_proxy():
    """config.yaml에서 proxy 필드를 로딩한다."""
    config = load_config()
    assert hasattr(config, "proxy")
    assert isinstance(config.proxy, str)
