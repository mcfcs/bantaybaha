"""Mirror data/raw to and from the team's private Cloud Storage bucket.

The download scripts stay the source of truth; the bucket is a shared cache so teammates don't have to re-run
the slow downloads. Only files listed in data/raw/MANIFEST.csv are synced, and pulls are checked against its sha256.

Auth reuses the Earth Engine login (`earthengine authenticate`); Application Default Credentials work too.
Pull needs Storage Object Viewer on the bucket; push needs write access on the bucket and Service Usage Consumer on the project.

Usage:
    python scripts/sync_data.py pull                  # fetch everything missing locally
    python scripts/sync_data.py pull dengue_hdx noah  # selected sources only
    python scripts/sync_data.py push                  # upload what the bucket lacks (creates the bucket if needed)
Options: --project hackathonproper --bucket bantay-baha-raw-hackathonproper
"""

import argparse
import csv
import io
from pathlib import Path

from google.cloud import storage

from download_data import RAW, sha256

PROJECT = "hackathonproper"
BUCKET = "bantay-baha-raw-hackathonproper"
LOCATION = "asia-southeast1"  # Singapore, closest region to the team
PREFIX = "raw/"


def client(project, quota=False):
    try:
        import google.auth
        cred, _ = google.auth.default()
    except Exception:  # noqa: BLE001 - no ADC, fall back to the Earth Engine login
        import ee
        cred = ee.data.get_persistent_credentials()
    # billing calls to the project needs Service Usage Consumer on it; pulls work with bucket access alone
    return storage.Client(project=project, credentials=cred.with_quota_project(project) if quota else cred)


def read_manifest(text):
    return {r["path"]: r for r in csv.DictReader(io.StringIO(text))}


def write_manifest(rows):
    with open(RAW / "MANIFEST.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["source", "path", "bytes", "sha256", "url"])
        w.writeheader()
        w.writerows(sorted(rows.values(), key=lambda r: r["path"]))


def push(cl, name, sources):
    bucket = cl.lookup_bucket(name)
    if bucket is None:
        bucket = cl.bucket(name)
        bucket.iam_configuration.uniform_bucket_level_access_enabled = True
        bucket.iam_configuration.public_access_prevention = "enforced"  # team-only: dataset licences differ
        bucket = cl.create_bucket(bucket, location=LOCATION)
        print(f"created gs://{name} in {LOCATION}")
    remote = {b.name: b for b in cl.list_blobs(name, prefix=PREFIX)}
    rows = read_manifest((RAW / "MANIFEST.csv").read_text())
    n = 0
    for rel, r in rows.items():
        if sources and r["source"] not in sources:
            continue
        b = remote.get(PREFIX + rel)
        if b is not None and b.size == int(r["bytes"]) and (b.metadata or {}).get("sha256") == r["sha256"]:
            continue
        blob = bucket.blob(PREFIX + rel, chunk_size=32 << 20)  # resumable, in 32 MB chunks
        blob.metadata = {"sha256": r["sha256"], "source": r["source"]}
        blob.upload_from_filename(RAW / rel, timeout=600)
        n += 1
        print(f"  up    {rel}  {int(r['bytes']) / 1e6:.1f} MB")
    bucket.blob(PREFIX + "MANIFEST.csv").upload_from_filename(RAW / "MANIFEST.csv")
    print(f"{n} files uploaded; gs://{name}/{PREFIX} is in sync with MANIFEST.csv")


def pull(cl, name, sources):
    bucket = cl.bucket(name)
    remote = read_manifest(bucket.blob(PREFIX + "MANIFEST.csv").download_as_text())
    local = read_manifest((RAW / "MANIFEST.csv").read_text()) if (RAW / "MANIFEST.csv").exists() else {}
    n = 0
    for rel, r in remote.items():
        if sources and r["source"] not in sources:
            continue
        dest = RAW / rel
        if dest.exists() and dest.stat().st_size == int(r["bytes"]):
            local.setdefault(rel, r)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        bucket.blob(PREFIX + rel).download_to_filename(tmp, timeout=600)
        if sha256(tmp) != r["sha256"]:
            tmp.unlink()
            raise RuntimeError(f"sha256 mismatch for {rel}; nothing written")
        tmp.replace(dest)
        local[rel] = r
        n += 1
        print(f"  down  {rel}  {int(r['bytes']) / 1e6:.1f} MB")
    write_manifest(local)
    print(f"{n} files downloaded into {RAW}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["push", "pull"])
    ap.add_argument("sources", nargs="*")
    ap.add_argument("--project", default=PROJECT)
    ap.add_argument("--bucket", default=BUCKET)
    a = ap.parse_args()
    (push if a.action == "push" else pull)(client(a.project, quota=a.action == "push"), a.bucket, set(a.sources))
