# Unchanged File Migration Manifest

**Date:** 2026-08-07
**Source:** `D:\repos\Torn - Company Data Puller`
**Destination:** `E:\repos\Torn Company Assistant (Web)`

The desktop repository remains intact. Only files requiring no content changes were copied.

## Copied unchanged

| Source | Destination | SHA-256 |
| --- | --- | --- |
| `app/profit_calc.py` | `backend/src/tca_web/domain/profit_calc.py` | `D5E437427F9DECEBC0DD5F2AD72FDD2D959BDF8F25CF3D0EFFD33BF3504524EC` |
| `app/ranking_calc.py` | `backend/src/tca_web/domain/ranking_calc.py` | `673CDC79698082289D72D27A39C1D9CDC7EEA814B6E84074C5E19271BDC7D96E` |
| `app/income_tracking.py` | `backend/src/tca_web/domain/income_tracking.py` | `C8984C33A586B42C04A572C8C2907F4667D1682DBEBA04C811493A88B783AF03` |
| `app/checksum.py` | `backend/src/tca_web/domain/checksum.py` | `656A18F02742A56FD1835BF8FCC31501123C96E985E3F58E3840ED5349E92985` |
| `TCA-v3.ico` | `frontend/public/favicon.ico` | `ACDEF40EBCC9E76168D120A4CACC7C00B3821C36B8664B34C85D1F9B44107A74` |

## Compatibility boundary

The Python files remain byte-for-byte copies and are importable, but they retain legacy formatting and partial type annotations. Narrow per-file Ruff and MyPy exceptions preserve their hashes until Phase 1 completes their type modernization. Their reusable desktop unit tests have been ported to the web package and remain green. They are not connected to API endpoints yet.

## Deferred because edits are required

- Torn and Torn Stats clients require asynchronous `httpx` integration and server-side secret handling.
- Employee efficiency imports desktop configuration and file logging.
- Collector, settings, persistence, scheduling, and company modules are desktop-, Google-, or Windows-bound.
- Remaining collector, persistence, and GUI tests require PostgreSQL fixtures and removal of Google, Tkinter, or desktop-settings assumptions.
- Privacy, terms, EULA, and hosted pages require web-hosting and PostgreSQL policy updates.
- Desktop build files, executables, checksums, Firebase files, logs, caches, and local credentials are not web-project assets.
