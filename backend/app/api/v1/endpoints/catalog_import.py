"""Staff catalogue import (module 8; TC-15).

Every route requires 'catalog:manage' (administrator and sales). Reading, checking and applying
rows is in app.services.catalog_import; file formats and templates in app.services.import_files.
Any catalogue manager may read any import job: jobs hold only counts and row/column errors, no
personal data, and the catalogue is shared by all catalogue staff.
"""

import re
import uuid
from pathlib import PurePath
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.api.v1.responses import ERR, FORBIDDEN_403, UNAUTHORIZED_401, VALIDATION_422, ResponseMap
from app.core.dependencies import require_permission
from app.core.errors import PayloadTooLarge, field_error
from app.core.request_context import RequestContext, get_request_context
from app.core.roles import Permission
from app.db.session import get_db
from app.models.identity import User
from app.schemas.catalog_import import MAX_IMPORT_BYTES, MAX_IMPORT_ROWS, ImportJobResponse
from app.services.catalog_import import CatalogImportService
from app.services.import_files import (
    CSV_CONTENT_TYPE,
    XLSX_CONTENT_TYPE,
    csv_template,
    xlsx_template,
)

router = APIRouter(prefix="/staff", tags=["Staff Catalogue"])

CatalogManager = Annotated[User, Depends(require_permission(Permission.CATALOG_MANAGE))]
Db = Annotated[Session, Depends(get_db)]
Ctx = Annotated[RequestContext, Depends(get_request_context)]

PERMISSION_NOTE = "Requires 'catalog:manage' (administrator, sales)."
EXTENSIONS = {".csv": "csv", ".xlsx": "xlsx"}
FILENAME_MAX_LENGTH = 255
FILE_TOO_LARGE = "The file is larger than 10 MB."
TEMPLATE_NAME = "catalogue-import-template"


def _example(code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {"value": {"error": {"code": code, "message": message, "details": details}}}


def _content(**examples: dict[str, Any]) -> dict[str, Any]:
    return {"content": {"application/json": {"examples": examples}}}


GUARDED: ResponseMap = {
    401: {
        **UNAUTHORIZED_401[401],
        **_content(missing=_example("token_missing", "Authentication token is missing.")),
    },
    403: {
        **FORBIDDEN_403[403],
        **_content(
            role=_example(
                "permission_denied", "Access forbidden: requires 'catalog:manage' permission."
            )
        ),
    },
}
UPLOAD_ERRORS: ResponseMap = {
    413: {
        **ERR,
        "description": "file_too_large: the upload is larger than 10 MB. Checked while the body "
        "is received, before authentication",
        **_content(
            request_too_large=_example("file_too_large", "The upload is larger than 10 MB."),
            file_too_large=_example("file_too_large", FILE_TOO_LARGE),
        ),
    },
    422: {
        **VALIDATION_422[422],
        **_content(
            unsupported=_example(
                "validation_error",
                "Request validation failed.",
                [
                    {
                        "type": "value_error",
                        "loc": ["body", "file"],
                        "msg": "Upload a .csv or .xlsx file.",
                    }
                ],
            ),
            empty=_example(
                "validation_error",
                "Request validation failed.",
                [{"type": "value_error", "loc": ["body", "file"], "msg": "The file is empty."}],
            ),
        ),
    },
}
JOB_404: ResponseMap = {
    404: {
        **ERR,
        "description": "No import job with this ID",
        **_content(unknown=_example("import_job_not_found", "Import job not found.")),
    }
}


def _safe_filename(name: str | None, extension: str) -> str:
    base = PurePath((name or "").replace("\\", "/")).name
    base = re.sub(r"[\x00-\x1f\x7f]", "", base).strip()
    return (base or f"upload{extension}")[-FILENAME_MAX_LENGTH:]


def _read(file: UploadFile) -> bytes:
    data = file.file.read(MAX_IMPORT_BYTES + 1)
    if len(data) > MAX_IMPORT_BYTES:
        raise PayloadTooLarge(FILE_TOO_LARGE)
    return bytes(data)


@router.get(
    "/imports/template",
    summary="Download the catalogue import template",
    description=(
        f"{PERMISSION_NOTE} The header row of the import file (and, for xlsx, an Instructions "
        "sheet describing every column). It contains no data rows, so importing it unchanged "
        "changes nothing."
    ),
    response_class=Response,
    responses={
        **GUARDED,
        **VALIDATION_422,
        200: {
            "description": "The template file",
            "content": {"text/csv": {}, XLSX_CONTENT_TYPE: {}},
        },
    },
)
def download_template(
    current_user: CatalogManager,
    file_format: Annotated[Literal["csv", "xlsx"], Query(alias="format")],
) -> Response:
    if file_format == "csv":
        body, media_type = csv_template(), CSV_CONTENT_TYPE
    else:
        body, media_type = xlsx_template(), XLSX_CONTENT_TYPE
    return Response(
        content=body,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{TEMPLATE_NAME}.{file_format}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post(
    "/imports",
    response_model=ImportJobResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Import products and variants from a CSV or XLSX file",
    description=(
        f"{PERMISSION_NOTE} multipart/form-data with `file` (.csv in UTF-8 or .xlsx, at most "
        f"10 MB and {MAX_IMPORT_ROWS} data rows). The file is processed within the request. "
        "Every row is checked first; valid rows are then applied in one transaction (SKU "
        "matching: existing SKUs are updated, new ones created) and invalid rows are reported "
        "by row number and column. 201 returns the job: 'completed' (valid rows applied) or "
        "'failed' (the file was unusable; nothing changed). See docs/api/catalogue-import.md."
    ),
    responses={**GUARDED, **UPLOAD_ERRORS},
)
def upload_import(
    file: Annotated[UploadFile, File(description=".csv (UTF-8) or .xlsx, at most 10 MB")],
    current_user: CatalogManager,
    db: Db,
    ctx: Ctx,
) -> ImportJobResponse:
    extension = PurePath(file.filename or "").suffix.lower()
    file_format = EXTENSIONS.get(extension)
    if file_format is None:
        raise field_error(("body", "file"), "Upload a .csv or .xlsx file.")
    data = _read(file)
    if not data:
        raise field_error(("body", "file"), "The file is empty.")
    job = CatalogImportService.run(
        db,
        current_user,
        _safe_filename(file.filename, extension),
        "csv" if file_format == "csv" else "xlsx",
        data,
        ctx,
    )
    return ImportJobResponse.model_validate(job)


@router.get(
    "/imports/{job_id}",
    response_model=ImportJobResponse,
    summary="Read an import job",
    description=f"{PERMISSION_NOTE} Status, row counts and row errors of one import.",
    responses={**GUARDED, **JOB_404, **VALIDATION_422},
)
def get_import(job_id: uuid.UUID, current_user: CatalogManager, db: Db) -> ImportJobResponse:
    return ImportJobResponse.model_validate(CatalogImportService.get(db, job_id))
