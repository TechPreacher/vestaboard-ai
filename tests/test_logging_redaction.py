import logging

from vboard import logging_setup


def test_registered_secret_is_redacted(caplog):
    logging_setup.configure_logging()
    logging_setup.register_secret("super-secret-key")
    logger = logging_setup.get_logger("test")
    with caplog.at_level(logging.INFO):
        logger.info("calling api with key super-secret-key now")
    assert "super-secret-key" not in caplog.text
    assert "***" in caplog.text


def test_secret_redacted_in_args(caplog):
    logging_setup.configure_logging()
    logging_setup.register_secret("tok_abc123")
    logger = logging_setup.get_logger("test")
    with caplog.at_level(logging.INFO):
        logger.info("token=%s", "tok_abc123")
    assert "tok_abc123" not in caplog.text


def test_secret_in_nonstring_arg_is_redacted(caplog):
    logging_setup.configure_logging()
    logging_setup.register_secret("nested_secret_42")
    logger = logging_setup.get_logger("test")
    with caplog.at_level(logging.INFO):
        logger.info("config: %s", {"api_key": "nested_secret_42"})
    assert "nested_secret_42" not in caplog.text
    assert "***" in caplog.text
