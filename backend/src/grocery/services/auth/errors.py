"""Ошибки аутентификации, не зависящие от транспорта."""


class AuthError(Exception):
    def __init__(self, message: str, *, code: str = "not_authenticated") -> None:
        super().__init__(message)
        self.code = code


class TooManyAttemptsError(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__("Слишком много попыток входа")
        self.retry_after = retry_after
