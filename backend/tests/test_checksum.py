from __future__ import annotations

import pytest

from tca_web.domain.checksum import (
    normalize_sha256,
    parse_checksum_manifest,
    sha256_file,
    verify_sha256,
)


def test_sha256_file_matches_known_digest(tmp_path):
    target = tmp_path / "TCA.exe"
    target.write_bytes(b"abc")

    assert sha256_file(target, chunk_size=1) == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


def test_normalize_sha256_accepts_uppercase():
    digest = "A" * 64

    assert normalize_sha256(digest) == "a" * 64


@pytest.mark.parametrize(
    "manifest",
    [
        "{digest}",
        "{digest}  TCA.exe",
        "{digest} *TCA.exe",
        "# release checksum\n\n{digest} *TCA.exe\n",
    ],
)
def test_manifest_formats(manifest):
    digest = "1" * 64

    assert parse_checksum_manifest(manifest.format(digest=digest), "TCA.exe") == digest


def test_manifest_selects_named_file_case_insensitively():
    first = "1" * 64
    second = "2" * 64
    manifest = f"{first} *Other.exe\n{second} *release/TCA.EXE\n"

    assert parse_checksum_manifest(manifest, "tca.exe") == second


@pytest.mark.parametrize(
    "manifest, message",
    [
        ("not-a-checksum", "Invalid checksum"),
        ("", "contains no SHA-256"),
        (f"{'1' * 64} *Other.exe", "No checksum entry"),
        (f"{'1' * 64}\n{'2' * 64}", "more than one entry"),
        (f"{'1' * 64} *TCA.exe\n{'2' * 64} *TCA.exe", "Conflicting checksums"),
    ],
)
def test_invalid_or_ambiguous_manifest_is_rejected(manifest, message):
    with pytest.raises(ValueError, match=message):
        parse_checksum_manifest(manifest, None if "more than one" in message else "TCA.exe")


def test_tampered_file_fails_verification(tmp_path):
    target = tmp_path / "TCA.exe"
    target.write_bytes(b"original")
    expected = sha256_file(target)
    target.write_bytes(b"tampered")

    assert not verify_sha256(target, expected)
