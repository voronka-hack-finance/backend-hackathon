import json
import time

from minio import Minio
from minio.error import S3Error
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from services.create_bucket_service.app.config import settings


def main() -> None:
    engine = _wait_for_postgres()
    _record_start(engine, settings.uploads_bucket)
    try:
        client = _wait_for_minio()
        if not client.bucket_exists(settings.uploads_bucket):
            client.make_bucket(settings.uploads_bucket)
        _apply_bucket_policy(client, settings.uploads_bucket, settings.uploads_bucket_policy)
        _record_finish(engine, settings.uploads_bucket, settings.uploads_bucket_policy, "completed", None)
    except Exception as exc:
        _record_finish(engine, settings.uploads_bucket, settings.uploads_bucket_policy, "failed", str(exc))
        raise


def _wait_for_postgres():
    engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
    deadline = time.monotonic() + 90
    while True:
        try:
            with engine.connect() as conn:
                conn.execute(text("select 1"))
            return engine
        except OperationalError:
            if time.monotonic() > deadline:
                raise
            time.sleep(2)


def _wait_for_minio() -> Minio:
    client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    deadline = time.monotonic() + 90
    while True:
        try:
            client.bucket_exists(settings.uploads_bucket)
            return client
        except Exception:
            if time.monotonic() > deadline:
                raise
            time.sleep(2)


def _record_start(engine, bucket_name: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                insert into bucket_bootstrap_runs(bucket_name, status, started_at, finished_at, error_message)
                values (:bucket_name, 'running', now(), null, null)
                on conflict (bucket_name) do update set
                  status = excluded.status,
                  started_at = excluded.started_at,
                  finished_at = null,
                  error_message = null
                """
            ),
            {"bucket_name": bucket_name},
        )


def _apply_bucket_policy(client: Minio, bucket_name: str, policy_name: str) -> None:
    normalized_policy = policy_name.strip().lower()
    if normalized_policy == "private":
        try:
            client.delete_bucket_policy(bucket_name)
        except S3Error as exc:
            if exc.code not in {"NoSuchBucketPolicy", "NoSuchBucketPolicyConfig"}:
                raise
        return
    if normalized_policy == "readonly":
        client.set_bucket_policy(bucket_name, _readonly_policy(bucket_name))
        return
    raise ValueError("UPLOADS_BUCKET_POLICY must be private or readonly")


def _readonly_policy(bucket_name: str) -> str:
    return json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"AWS": ["*"]},
                    "Action": ["s3:GetObject"],
                    "Resource": [f"arn:aws:s3:::{bucket_name}/*"],
                }
            ],
        }
    )


def _record_finish(engine, bucket_name: str, policy_name: str, status: str, error_message: str | None) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                update bucket_bootstrap_runs
                set status = cast(:status as varchar),
                    policy_name = :policy_name,
                    policy_applied_at = case when cast(:status as varchar) = 'completed' then now() else policy_applied_at end,
                    finished_at = now(),
                    error_message = :error_message
                where bucket_name = :bucket_name
                """
            ),
            {"bucket_name": bucket_name, "policy_name": policy_name, "status": status, "error_message": error_message},
        )


if __name__ == "__main__":
    main()
