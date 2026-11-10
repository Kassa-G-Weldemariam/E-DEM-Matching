import uuid

from fastapi import APIRouter, Response, status

from app.api.deps import CurrentUser, DbSession, DonorUser
from app.core.responses import success_response
from app.schemas.device import DeviceRegisterRequest, DeviceResponse
from app.services import devices as device_service
from app.services.ownership import get_device_for_user

router = APIRouter(prefix="/devices", tags=["Devices"])


@router.post("", status_code=status.HTTP_201_CREATED)
def register_device(
    data: DeviceRegisterRequest, user: DonorUser, db: DbSession, response: Response
):
    """Register or refresh this phone's push token. 201 when new, 200 when it already existed."""
    device, created = device_service.register_device(db, user, data)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return success_response(
        DeviceResponse.model_validate(device).model_dump(mode="json"),
        "Device registered" if created else "Device updated",
    )


@router.delete("/{device_id}")
def remove_device(device_id: uuid.UUID, user: CurrentUser, db: DbSession):
    """Remove a device. The app calls this on logout, with the id it got when registering."""
    device = get_device_for_user(db, device_id, user)
    device_service.delete_device(db, device)
    return success_response(None, "Device removed")
