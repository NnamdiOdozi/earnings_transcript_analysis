import pytest

from earnings import config


def test_validate_provider_rejects_unknown_name():
    with pytest.raises(ValueError):
        config._validate_provider("exaa")


def test_validate_provider_accepts_tavily():
    assert config._validate_provider("tavily") == "tavily"
