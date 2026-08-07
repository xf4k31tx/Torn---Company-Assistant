from __future__ import annotations

import hashlib
import hmac
import re
from pathlib import Path


_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_MANIFEST_RE = re.compile(r"^\s*([0-9a-fA-F]{64})(?:\s+(\*)?(.+?))?\s*$")


def normalize_sha256(value: str) -> str:
    digest = value.strip().lower()
    if not _SHA256_RE.fullmatch(digest):
        raise ValueError("Expected a 64-character SHA-256 checksum.")
    return digest


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    if chunk_size <= 0:
        raise ValueError("Chunk size must be greater than zero.")

    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        while chunk := source.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def parse_checksum_manifest(text: str, filename: str | Path | None = None) -> str:
    entries: list[tuple[str, str | None]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _MANIFEST_RE.fullmatch(line)
        if not match:
            raise ValueError(f"Invalid checksum manifest entry on line {line_number}.")
        digest, _binary_marker, entry_name = match.groups()
        entries.append((normalize_sha256(digest), entry_name.strip() if entry_name else None))

    if not entries:
        raise ValueError("The checksum manifest contains no SHA-256 checksum.")

    if filename is None:
        if len(entries) != 1:
            raise ValueError("The checksum manifest contains more than one entry.")
        return entries[0][0]

    target_name = Path(filename).name.casefold()
    matches = [
        digest
        for digest, entry_name in entries
        if entry_name is not None
        and Path(entry_name.replace("\\", "/")).name.casefold() == target_name
    ]
    if matches:
        if len(set(matches)) != 1:
            raise ValueError(f"Conflicting checksums found for {Path(filename).name}.")
        return matches[0]

    bare_entries = [digest for digest, entry_name in entries if entry_name is None]
    if len(entries) == 1 and len(bare_entries) == 1:
        return bare_entries[0]

    raise ValueError(f"No checksum entry found for {Path(filename).name}.")


def load_expected_sha256(
    manifest_path: str | Path,
    filename: str | Path | None = None,
) -> str:
    text = Path(manifest_path).read_text(encoding="utf-8-sig")
    return parse_checksum_manifest(text, filename)


def verify_sha256(path: str | Path, expected_sha256: str) -> bool:
    return hmac.compare_digest(sha256_file(path), normalize_sha256(expected_sha256))
