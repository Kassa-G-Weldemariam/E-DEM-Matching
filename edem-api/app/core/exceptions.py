class AppException(Exception):
    def __init__(self, message: str, code: str = "APP_ERROR", status_code: int = 400):
        self.message = message
        self.code = code
        self.status_code = status_code
        super().__init__(message)


class NotFoundException(AppException):
    def __init__(self, message: str = "Resource not found"):
        super().__init__(message=message, code="NOT_FOUND", status_code=404)


class UnauthorizedException(AppException):
    def __init__(self, message: str = "Unauthorized"):
        super().__init__(message=message, code="UNAUTHORIZED", status_code=401)


class ForbiddenException(AppException):
    def __init__(self, message: str = "Forbidden"):
        super().__init__(message=message, code="FORBIDDEN", status_code=403)


class EmailAlreadyRegisteredException(AppException):
    def __init__(self, message: str = "This email is already registered"):
        super().__init__(
            message=message, code="EMAIL_ALREADY_REGISTERED", status_code=409
        )


class InvalidCurrentPasswordException(AppException):
    def __init__(self, message: str = "The current password is incorrect"):
        super().__init__(
            message=message, code="INVALID_CURRENT_PASSWORD", status_code=400
        )


class AccountNotApprovedException(AppException):
    def __init__(
        self, message: str = "This account has not been approved by an Admin yet"
    ):
        super().__init__(message=message, code="ACCOUNT_NOT_APPROVED", status_code=403)


class BadRequestException(AppException):
    def __init__(self, message: str = "Bad request"):
        super().__init__(message=message, code="BAD_REQUEST", status_code=400)


class ProfileAlreadyExistsException(AppException):
    def __init__(self, message: str = "You have already created a profile"):
        super().__init__(
            message=message, code="PROFILE_ALREADY_EXISTS", status_code=409
        )


class InvalidStatusTransitionException(AppException):
    def __init__(
        self, message: str = "This action is no longer allowed in the current status"
    ):
        super().__init__(
            message=message, code="INVALID_STATUS_TRANSITION", status_code=409
        )
