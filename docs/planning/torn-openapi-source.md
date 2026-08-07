# Torn API v2 OpenAPI Source

## Authority

- Live upstream specification: `https://www.torn.com/swagger/openapi.json`
- Pinned project contract: `docs/planning/openapi.json`

The live Torn document is the upstream authority. The checked-in document is the exact contract used for implementation, tests, and reproducible builds. API work must consult the pinned contract, and intentional upstream updates must replace it as a reviewed change rather than silently changing application behavior.

## Current verification

Verified on 2026-08-07 with a project-specific `User-Agent`:

- OpenAPI: `3.1.0`
- Torn specification version: `6.6.1`
- Paths: `211`
- Schemas: `653`
- SHA-256: `232c9c506b5c45094cebf4d9f7650a50d5a1cba8f6c52bb62a14d047e306ca3f`
- Live and pinned files: byte-for-byte identical

## Update rule

When the live checksum changes, review the OpenAPI diff, update affected models and tests, run the complete backend and frontend validation suites, then replace the pinned file in the same reviewed change. Never update the pinned contract automatically in production.
