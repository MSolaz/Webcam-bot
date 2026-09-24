from types import SimpleNamespace

from webcam_bot.auth import is_authorized


def test_empty_allowlist_allows_everyone():
    assert is_authorized(SimpleNamespace(id=1), frozenset())


def test_allowlist_filters_users():
    allowed = frozenset({1, 2})
    assert is_authorized(SimpleNamespace(id=2), allowed)
    assert not is_authorized(SimpleNamespace(id=3), allowed)


def test_no_user_is_rejected():
    assert not is_authorized(None, frozenset())
