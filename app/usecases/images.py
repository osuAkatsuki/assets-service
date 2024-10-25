import io
import logging
import typing
from enum import Enum

from PIL import ImageFile

import settings
from app.adapters import rekognition
from app.adapters import s3
from app.api.authorization import AbstractAuthorization
from app.errors import Error
from app.errors import ErrorCode

ALLOWED_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
}

VIDEO_MIME_TYPES = {
    "image/gif",
    # TODO?: I think image/apng may be slipping past here
}

# https://docs.aws.amazon.com/rekognition/latest/dg/moderation.html#moderation-api
DISALLOWED_MODERATION_LABELS = {
    "Explicit Nudity",
    "Explicit Sexual Activity",
    "Sex Toys",
    "Obstructed Intimate Parts",
    "Self-Harm",
    "Blood & Gore",
    "Death and Emaciation",
    "Hate Symbols",
}


class ImageType(str, Enum):
    USER_AVATAR = "user_avatar"
    USER_PROFILE_BACKGROUND = "user_profile_background"
    CLAN_ICON = "clan_icon"
    SCREENSHOT = "screenshot"

    def get_s3_folder(self) -> str:
        return {
            ImageType.USER_AVATAR: "avatars",
            ImageType.USER_PROFILE_BACKGROUND: "profile-backgrounds",
            ImageType.CLAN_ICON: "clan-icons",
            ImageType.SCREENSHOT: "screenshots",
        }[self]

    def get_max_single_dimension_size(self) -> int:
        return {
            ImageType.USER_AVATAR: 512,
            ImageType.USER_PROFILE_BACKGROUND: 1920,
            ImageType.CLAN_ICON: 256,
            ImageType.SCREENSHOT: 1920,
        }[self]


def should_disallow_upload(moderation_labels: list[str]) -> bool:
    return any(l in DISALLOWED_MODERATION_LABELS for l in moderation_labels)


def _get_image_file_from_data(data: bytes) -> ImageFile.ImageFile:
    parser = ImageFile.Parser()
    parser.feed(data)
    return typing.cast(ImageFile.ImageFile, parser.close())


async def upload_image(
    image_type: ImageType,
    image_content: bytes,
    no_ext_file_name: str,
    authorization: AbstractAuthorization,
) -> None | Error:
    try:
        image = _get_image_file_from_data(image_content)
        image_format = image.format
        if image_format is None:
            return Error("Invalid Image Format", ErrorCode.INVALID_CONTENT)

        image_mime_type = image.get_format_mimetype()
        if image_mime_type not in ALLOWED_MIME_TYPES:
            return Error("Invalid Image Content Type", ErrorCode.INVALID_CONTENT)

        # Resize image if it is too large. Maintain aspect ratio.
        max_single_dimension_size = image_type.get_max_single_dimension_size()
        if (
            image.width > max_single_dimension_size
            or image.height > max_single_dimension_size
        ):
            biggest_dimension = max(image.width, image.height)
            aspect_ratio = max_single_dimension_size / biggest_dimension
            new_width = int(image.width * aspect_ratio)
            new_height = int(image.height * aspect_ratio)
            image = image.resize((new_width, new_height))

        with io.BytesIO() as f:
            image.save(f, format=image_format)
            image_content = f.getvalue()
    except Exception:
        logging.exception(
            "Failed to process image",
            extra={
                "file_name": no_ext_file_name,
                "image_type": image_type,
                "image_size": len(image_content),
                "authorization": authorization.format_for_logs(),
            },
        )
        return Error("Invalid Image", ErrorCode.INVALID_CONTENT)

    if settings.SHOULD_FILTER_INAPPROPRIATE_CONTENT:
        if (
            # TODO: we do not yet support video types from a technical lens
            #       we'll likely want to add this (at least) for gif profile backgrounds
            image_mime_type not in VIDEO_MIME_TYPES
            # TODO: we do not yet support screenshots due to high qps/cost
            and image_type is not ImageType.SCREENSHOT
        ):
            moderation_labels = await rekognition.detect_moderation_labels(
                image_content,
            )
            if moderation_labels is None:
                return Error("Service Unavailable", ErrorCode.SERVICE_UNAVAILABLE)

            if should_disallow_upload(moderation_labels):
                # TODO: store/audit log these occurrences persistently
                logging.warning(
                    "Rejected image due to moderation labels",
                    extra={
                        "image_type": image_type,
                        "file_name": no_ext_file_name,
                        "moderation_labels": moderation_labels,
                        "authorization": authorization.format_for_logs(),
                    },
                )
                return Error("Inappropriate Content", ErrorCode.INAPPROPRIATE_CONTENT)

    await s3.upload(
        body=image_content,
        file_name=f"{no_ext_file_name}.{image_format.lower()}",
        directory=image_type.get_s3_folder(),
        content_type=image_mime_type,
    )
    logging.info(
        "Uploaded image",
        extra={
            "file_name": no_ext_file_name,
            "image_type": image_type,
            "image_size": len(image_content),
            "authorization": authorization.format_for_logs(),
        },
    )

    return None


async def delete_image(
    image_type: ImageType,
    no_ext_file_name: str,
    authorization: AbstractAuthorization,
) -> None | Error:
    for ext in ["png", "jpg", "jpeg", "gif", "webp"]:
        await s3.delete(
            file_name=f"{no_ext_file_name}.{ext}",
            directory=image_type.get_s3_folder(),
        )
    logging.info(
        "Deleted Image",
        extra={
            "file_name": no_ext_file_name,
            "image_type": image_type,
            "authorization": authorization.format_for_logs(),
        },
    )
