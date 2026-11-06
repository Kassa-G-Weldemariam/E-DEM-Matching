import uuid

from pydantic import BaseModel, ConfigDict


class BloodBankPublic(BaseModel):
    """What anyone may see about a blood bank. No phone, owner or approval status."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    address: str
    city: str
    latitude: float
    longitude: float
    distance_km: float | None = None  # only filled when the caller sends lat and lng
