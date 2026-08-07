# Architecture Decision Record

**Title:** Use React Router only in client-side Declarative Mode
**Status:** Accepted
**Date:** 2026-08-07

## Context

React Router Framework Mode and unstable RSC paths have had server-side security advisories. CVE-2026-42211 affects Framework Mode before 7.14.2, while the `__manifest` denial-of-service issue is CVE-2026-42342 and affects Framework Mode before 7.15.0. GitHub advisory GHSA-qwww-vcr4-c8h2 lists 7.18.2 as the patched 7.x release for the unstable RSC CSRF bypass.

## Decision

Pin React Router to 7.18.2 and use only client-side Declarative Mode through `BrowserRouter`, `Routes`, and `Route`. TanStack Query will handle remote data.

Do not add React Router Framework Mode, its Vite plugin, route modules, server actions, SSR hydration, RSC packages, unstable RSC APIs, or a `__manifest` endpoint without a new security review and ADR.

The FastAPI service remains the only application backend. The React application is built as static browser assets.

The npm advisory cache currently reports GHSA-qwww-vcr4-c8h2 against 7.18.2 even though the current GitHub vendor advisory lists 7.18.2 as patched. This documented exception is limited to that advisory and this non-RSC configuration; all other high or critical findings remain release blockers.

## Consequences

- The cited Framework/RSC attack paths are absent from the application.
- Routing remains simple and compatible with the Vite SPA.
- Framework loaders, actions, SSR, and RSC features are unavailable.
- Dependency audits and vendor advisories must be reviewed whenever React Router changes.

## References

- https://github.com/remix-run/react-router/blob/main/docs/start/modes.md
- https://nvd.nist.gov/vuln/detail/CVE-2026-42211
- https://nvd.nist.gov/vuln/detail/CVE-2026-42342
- https://github.com/remix-run/react-router/security/advisories/GHSA-qwww-vcr4-c8h2
