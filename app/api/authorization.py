from abc import ABC
from abc import abstractmethod
from typing import Any

from fastapi import Header
from fastapi import HTTPException

import settings


class AbstractAuthorization(ABC):
    @abstractmethod
    def format_for_logs(self) -> dict[str, Any]:
        pass


class AdminAuthorization(AbstractAuthorization):
    def format_for_logs(self) -> dict[str, Any]:
        return {"is_administrator": True}


def authorize_admin(
    api_key: str = Header(..., alias="X-Api-Key"),
) -> AdminAuthorization:
    if api_key != settings.APP_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

    return AdminAuthorization()
