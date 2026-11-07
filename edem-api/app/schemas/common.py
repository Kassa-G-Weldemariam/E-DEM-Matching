"""Field types shared by several schemas."""

import re
from typing import Annotated

from pydantic import AfterValidator, Field, StringConstraints

_PHONE_PATTERN = re.compile(r"^\+?[0-9]{9,15}$")


def _clean_phone(value: str) -> str:
    cleaned = re.sub(r"[\s\-()]", "", value)
    if not _PHONE_PATTERN.match(cleaned):
        raise ValueError("Enter a valid phone number, for example +251111234567")
    return cleaned


# Spaces, dashes and brackets are removed. A leading + is allowed.
PhoneNumber = Annotated[
    str, StringConstraints(max_length=32), AfterValidator(_clean_phone)
]

Latitude = Annotated[float, Field(ge=-90, le=90)]
Longitude = Annotated[float, Field(ge=-180, le=180)]
