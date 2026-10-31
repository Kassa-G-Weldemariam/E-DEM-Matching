from typing import Any


def success_response(data: Any = None, message: str = "Success"):
    return {
        "success": True,
        "message": message,
        "data": data,
    }


def error_response(message: str, code: str = "ERROR", details: Any = None):
    return {
        "success": False,
        "error": {
            "code": code,
            "message": message,
            "details": details,
        },
    }
