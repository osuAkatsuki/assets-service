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


@router.post("/api/v1/clans/{clan_id}/icon")
async def upload_clan_icon(
    clan_id: int,
    file_content: bytes = File(...),
    authorization: AdminAuthorization = Depends(authorize_admin),
):
    data = await app.usecases.images.upload_image(
        image_type=ImageType.CLAN_ICON,
        image_content=file_content,
        no_ext_file_name=f"{clan_id}",
        authorization=authorization,
    )
    if isinstance(data, Error):
        return Response(
            status_code=_get_status_code_for_error(data.code),
            content=data.user_feedback,
        )
    return Response(status_code=201)


@router.get("/api/v1/clan-icons/{file_path:path}")
@router.get("/public/api/v1/clan-icons/{file_path:path}")
async def get_clan_icon(file_path: str):
    if ".." in file_path or "/" in file_path:
        return Response(status_code=404)

    download_response = await s3.download(
        file_path,
        directory=ImageType.CLAN_ICON.get_s3_folder(),
    )
    if download_response is None:
        logging.warning(
            "Failed to serve non-existent clan icon",
            extra={"file_path": file_path},
        )
        return Response(status_code=404)

    logging.debug("Served clan icon", extra={"file_path": file_path})

    return Response(
        content=download_response["body"],
        media_type=download_response["content_type"],
    )
