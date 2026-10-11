"""Authenticated HTTP adapter for the shared update service."""

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field

from app.config import Settings
from app.security import Principal, SecurityError, require_permission
from knemora_bootstrap.update import UpdateError, UpdateService


class StartUpdateRequest(BaseModel):
    target_sha: str = Field(pattern=r"^[0-9a-f]{40}$")


def create_update_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/v1/updates", tags=["updates"])

    def service(request: Request) -> UpdateService:
        return cast(UpdateService, request.app.state.update_service)

    def trusted_origin(request: Request) -> None:
        if request.headers.get("Origin") != settings.web_origin:
            raise SecurityError(
                "Update mutations require the configured local web origin.",
                status_code=status.HTTP_403_FORBIDDEN,
                error_type="urn:knemora:error:update-origin",
            )

    def translate(error: UpdateError) -> SecurityError:
        return SecurityError(
            str(error),
            status_code=status.HTTP_409_CONFLICT,
            error_type="urn:knemora:error:update-conflict",
        )

    @router.get("")
    def read_update(
        _: Annotated[Principal, Depends(require_permission("settings.manage"))],
        updates: Annotated[UpdateService, Depends(service)],
    ) -> dict[str, Any]:
        result = updates.cached().to_dict()
        result["active_job"] = updates.active_job()
        return result

    @router.get("/preview")
    def preview_update(
        _: Annotated[Principal, Depends(require_permission("settings.manage"))],
        updates: Annotated[UpdateService, Depends(service)],
    ) -> dict[str, Any]:
        return updates.cached().to_dict()

    @router.post("/check")
    def check_update(
        _: Annotated[Principal, Depends(require_permission("settings.manage"))],
        __: Annotated[None, Depends(trusted_origin)],
        updates: Annotated[UpdateService, Depends(service)],
    ) -> dict[str, Any]:
        return updates.check().to_dict()

    @router.post("/jobs", status_code=status.HTTP_202_ACCEPTED)
    def start_update(
        body: StartUpdateRequest,
        _: Annotated[Principal, Depends(require_permission("settings.manage"))],
        __: Annotated[None, Depends(trusted_origin)],
        updates: Annotated[UpdateService, Depends(service)],
    ) -> dict[str, Any]:
        try:
            job = updates.create_job(body.target_sha)
            if job["status"] == "queued" and not job.get("deduplicated"):
                updates.spawn_job(str(job["id"]))
            return job
        except UpdateError as error:
            raise translate(error) from error

    @router.get("/jobs/{job_id}")
    def read_update_job(
        job_id: str,
        _: Annotated[Principal, Depends(require_permission("settings.manage"))],
        updates: Annotated[UpdateService, Depends(service)],
    ) -> dict[str, Any]:
        try:
            return updates.read_job(job_id)
        except UpdateError as error:
            raise translate(error) from error

    return router


__all__ = ["create_update_router"]
