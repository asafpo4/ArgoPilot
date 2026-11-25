"""Plot photos: the bytes live in S3, the registry database keeps only the key and the type."""

import logging
from typing import Annotated, Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile

import db
from db import get_db
from validation import contains_nul

logger = logging.getLogger("registry.photos")

router = APIRouter(prefix="/v1")

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_PHOTO_BYTES = 5 * 1024 * 1024

# One row per plot. A plot that is deleted takes its row with it (ON DELETE CASCADE).
# IF NOT EXISTS: the table is made on first use, also in a database that was seeded before photos existed.
CREATE_PHOTO_TABLE = (
    "CREATE TABLE IF NOT EXISTS plot_photos ("
    "plot_id TEXT PRIMARY KEY REFERENCES plots(id) ON DELETE CASCADE, "
    "s3_key TEXT NOT NULL, "
    "content_type TEXT NOT NULL)"
)

# A second upload for the same plot replaces the row.
SAVE_PHOTO = (
    "INSERT INTO plot_photos (plot_id, s3_key, content_type) VALUES (:plot_id, :s3_key, :content_type) "
    "ON CONFLICT (plot_id) DO UPDATE SET s3_key = excluded.s3_key, content_type = excluded.content_type"
)


def ensure_photo_table(conn: db.Connection) -> None:
    conn.execute(CREATE_PHOTO_TABLE)
    conn.commit()


def find_farm_id(conn: db.Connection, plot_id: str) -> str:
    """The plot's current farm_id. 404 if the plot does not exist."""
    if contains_nul(plot_id):
        raise HTTPException(status_code=404, detail="Plot not found")
    row = conn.execute("SELECT farm_id FROM plots WHERE id = :id", {"id": plot_id}).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Plot not found")
    return row["farm_id"]


def s3_client(request: Request) -> Any:
    """A new S3 client for this request. Credentials are never passed: boto3 finds them itself."""
    return boto3.client("s3", region_name=request.app.state.settings.AWS_REGION)


def storage_unavailable(exc: Exception) -> HTTPException:
    """Log the boto3 error and return the 503 to raise. It is returned, not raised (see db.Connection)."""
    logger.warning("Photo storage unavailable: %s: %s", type(exc).__name__, exc)
    return HTTPException(status_code=503, detail="Photo storage unavailable")


@router.post("/plots/{plot_id}/photo", status_code=201)
def upload_photo(
    plot_id: str,
    file: UploadFile,
    request: Request,
    conn: Annotated[db.Connection, Depends(get_db)],
) -> dict[str, str]:
    ensure_photo_table(conn)
    farm_id = find_farm_id(conn, plot_id)

    # Checked before S3 is called. One byte over the limit is enough to know the file is too big.
    content_type = file.content_type
    data = file.file.read(MAX_PHOTO_BYTES + 1)
    if not data:
        raise HTTPException(status_code=422, detail="The file is empty")
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=422, detail="The file must be image/jpeg, image/png or image/webp")
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=422, detail="The file is larger than 5 MB")

    key = f"{farm_id}/{plot_id}/photo"
    try:
        s3_client(request).put_object(
            Bucket=request.app.state.settings.AWS_S3_BUCKET,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
    except (BotoCoreError, ClientError) as exc:
        error = storage_unavailable(exc)
    else:
        # Saved only after S3 accepted the bytes, so a failed upload leaves the stored key as it was.
        conn.execute(SAVE_PHOTO, {"plot_id": plot_id, "s3_key": key, "content_type": content_type})
        conn.commit()
        return {"plot_id": plot_id, "key": key, "content_type": content_type}
    raise error  # Outside the handler, so the boto3 error is not kept in __context__.


@router.get("/plots/{plot_id}/photo")
def download_photo(
    plot_id: str,
    request: Request,
    conn: Annotated[db.Connection, Depends(get_db)],
) -> Response:
    ensure_photo_table(conn)
    find_farm_id(conn, plot_id)
    row = conn.execute(
        "SELECT s3_key, content_type FROM plot_photos WHERE plot_id = :id", {"id": plot_id}
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Plot has no photo")

    try:
        obj = s3_client(request).get_object(Bucket=request.app.state.settings.AWS_S3_BUCKET, Key=row["s3_key"])
        data = obj["Body"].read()
    except (BotoCoreError, ClientError) as exc:
        error = storage_unavailable(exc)
    else:
        return Response(content=data, media_type=row["content_type"])
    raise error
