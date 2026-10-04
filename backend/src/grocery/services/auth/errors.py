"""Ошибки аутентификации, не зависящие от транспорта."""


class AuthError(Exception):
    def __init__(self, message: str, *, code: str = "not_authenticated") -> None:
        super().__init__(message)
        self.code = code


class TooManyAttemptsError(Exception):
    def __init__(self, retry_after: int, *, message: str = "Слишком много попыток входа") -> None:
        super().__init__(message)
        self.retry_after = retry_after
