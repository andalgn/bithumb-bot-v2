"""프록시 설정 로딩 테스트."""

from app.config import load_config
from market.bithumb_api import BithumbClient


def test_load_config_has_proxy():
    """config.yaml에서 proxy 필드를 로딩한다."""
    config = load_config()
    assert hasattr(config, "proxy")
    assert isinstance(config.proxy, str)


def test_bithumb_client_accepts_proxy():
    """BithumbClient가 proxy 파라미터를 받는다."""
    client = BithumbClient(
        api_key="test",
        api_secret="test",
        proxy="http://127.0.0.1:1081",
    )
    assert client._proxy == "http://127.0.0.1:1081"


def test_bithumb_client_proxy_default_empty():
    """proxy 미지정 시 빈 문자열."""
    client = BithumbClient(api_key="test", api_secret="test")
    assert client._proxy == ""
