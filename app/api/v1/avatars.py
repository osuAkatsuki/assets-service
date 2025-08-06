import logging

from fastapi import APIRouter
from fastapi import Depends
from fastapi import File
from fastapi import Response

import app.usecases.images
import settings
from app.adapters import s3
from app.api.authorization import AdminAuthorization
from app.api.authorization import authorize_admin
from app.errors import Error
from app.errors import ErrorCode
from app.usecases.images import ImageType

router = APIRouter()


def _get_status_code_for_error(error_code: ErrorCode) -> int:
    try:
        return {
            ErrorCode.INVALID_CONTENT: 400,
            ErrorCode.INAPPROPRIATE_CONTENT: 400,
            ErrorCode.SERVICE_UNAVAILABLE: 503,
        }[error_code]
    except KeyError:
        logging.warning(
            "Unmapped error code while resolving http status code",
            extra={"error_code": error_code},
        )
        return 500


@router.post("/api/v1/users/{user_id}/avatar")
async def upload_avatar(
    user_id: int,
    file_content: bytes = File(...),
    authorization: AdminAuthorization = Depends(authorize_admin),
):
    data = await app.usecases.images.upload_image(
        image_type=ImageType.USER_AVATAR,
        image_content=file_content,
        no_ext_file_name=f"{user_id}",
        authorization=authorization,
    )
    if isinstance(data, Error):
        return Response(
            status_code=_get_status_code_for_error(data.code),
            content=data.user_feedback,
        )
    return Response(status_code=204)


@router.get("/api/v1/avatars/{file_path:path}")
@router.get("/public/api/v1/avatars/{file_path:path}")
async def get_avatar(file_path: str):
    if ".." in file_path or "/" in file_path:
        return Response(status_code=404)

    if not file_path.endswith(".png"):
        file_path += ".png"

    download_response = await s3.download(file_path, "avatars")
    if download_response is None:
        # fallback to a default avatar so we don't need to
        # duplicate the default avatar for all of our userbase
        download_response = await s3.download(
            file_name=settings.DEFAULT_AVATAR_FILENAME,
            directory="avatars",
        )
        if download_response is None:
            logging.warning(
                "Failed to serve non-existent user avatar and default avatar is missing",
                extra={"file_path": file_path},
            )
            return Response(status_code=404)

        file_path = settings.DEFAULT_AVATAR_FILENAME

    logging.debug("Served user avatar", extra={"file_path": file_path})

    return Response(
        content=download_response["body"],
        media_type=download_response["content_type"],
    )


@router.delete("/api/v1/users/{user_id}/avatar")
async def delete_avatar(
    user_id: int,
    authorization: AdminAuthorization = Depends(authorize_admin),
):
    data = await app.usecases.images.delete_image(
        image_type=ImageType.USER_AVATAR,
        no_ext_file_name=f"{user_id}",
        authorization=authorization,
    )
    if isinstance(data, Error):
        return Response(
            status_code=_get_status_code_for_error(data.code),
            content=data.user_feedback,
        )
    return Response(status_code=204)
