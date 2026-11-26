"""Rebuild the pinned Temporal CLI 1.9.1 binary from the shipped archive pieces."""
import hashlib
import io
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PARTS = ROOT / "parts"
TARGET = ROOT / "temporal.exe"
ARCHIVE = "temporal-cli-1.9.1.zip"
ARCHIVE_SHA256 = "f45234840e06733ebc045244e36d0a64cc27c6348952d40f06837a9f94cc21b5"
EXPECTED = "c49d7f0d9f6a7ae5aed3b97a259070c1cee7bf7e7543be9b4c602109caf3c806"


def main():
    pieces = sorted(PARTS.glob(ARCHIVE + ".part*"))
    if not pieces:
        raise SystemExit("no Temporal CLI pieces in " + str(PARTS))
    data = b"".join(path.read_bytes() for path in pieces)
    digest = hashlib.sha256(data).hexdigest()
    if digest != ARCHIVE_SHA256:
        raise SystemExit("archive sha256 mismatch: " + digest)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if archive.namelist() != ["temporal.exe"]:
            raise SystemExit("unexpected archive contents: " + str(archive.namelist()))
        payload = archive.read("temporal.exe")
    digest = hashlib.sha256(payload).hexdigest()
    if digest != EXPECTED:
        raise SystemExit("sha256 mismatch: " + digest)
    TARGET.write_bytes(payload)
    print("wrote", TARGET, "sha256", digest)


if __name__ == "__main__":
    main()
