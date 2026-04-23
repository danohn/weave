from app.core.config import Settings


def test_session_cookie_secure_defaults_false_without_weave_domain():
    settings = Settings(_env_file=None, WEAVE_DOMAIN="")
    assert settings.session_cookie_secure is False


def test_session_cookie_secure_defaults_true_with_weave_domain():
    settings = Settings(_env_file=None, WEAVE_DOMAIN="weave.example.com")
    assert settings.session_cookie_secure is True


def test_session_cookie_secure_can_be_overridden_explicitly():
    settings = Settings(
        _env_file=None,
        WEAVE_DOMAIN="weave.example.com",
        SESSION_COOKIE_SECURE=False,
    )
    assert settings.session_cookie_secure is False
