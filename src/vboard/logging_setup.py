import logging

_SECRETS: set[str] = set()
_CONFIGURED = False


def register_secret(value: str) -> None:
    if value:
        _SECRETS.add(value)


class _RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()  # applies record.args to record.msg
        record.msg = self._scrub(message)
        record.args = None
        return True

    @staticmethod
    def _scrub(value: str) -> str:
        out = value
        for secret in tuple(_SECRETS):   # snapshot: safe under concurrent register_secret
            if secret:
                out = out.replace(secret, "***")
        return out


def configure_logging(level: int = logging.INFO) -> None:
    global _CONFIGURED
    root = logging.getLogger()
    root.setLevel(level)
    if not _CONFIGURED:
        handler = logging.StreamHandler()
        handler.addFilter(_RedactionFilter())
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        root.addHandler(handler)
        _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.addFilter(_RedactionFilter())
    return logger
