"""
Employee effectiveness + tornstats-methodology position-efficiency
projections, plus an optional capacity-constrained position assignment.

Three distinct numbers can be surfaced per employee:

  - "effectiveness" (Torn's own, from v2/company/employees) - the real,
    current effectiveness this employee has *in their current position*:
    working_stats, settled_in, director_education, addiction, inactivity,
    management, book, merits, summing to `total`.

  - "W.S. Eff." / "Optimal Position (Global)" (Tornstats' methodology, via
    the tornstats.com /efficiency endpoint) - a *projection*, ignoring any
    headcount limits, of how effective this employee's raw work stats
    (manual_labor/intelligence/endurance) would be at EVERY position your
    company type offers. `best_fit_position`/`best_fit_efficiency` is
    simply this employee's single highest projected position - unconstrained,
    so two employees can "want" the same position.

  - "Optimal Position (Priority)" (this module's assign_positions()) - the
    position this employee actually gets once positions are filled in a
    chosen priority order, each capped at its configured max headcount, and
    the whole roster capped at the company's total employee capacity. This
    is the answer to "who's the best person for each seat, filled in the
    order that matters to me", not just "what's each person's best seat".

Tornstats' /efficiency endpoint has no notion of "your" company - it
returns a block per company type in the game, e.g.:
    {"1": {"company": "Hair Salon", "Stylist": 165, ...}, "7": {...}, ...
     "stats": {...}, "status": true, "message": "..."}

The numeric key each block is filed under ("1", "7", ...) is Tornstats'
copy of Torn's own company_type id (v2/company/profile's "type"."id") -
confirmed by comparing a real profile response against a real efficiency
response for the same company. That id match is authoritative and is now
the primary way find_company_type_block() identifies the right block.

Tornstats' "company" text label is NOT reliable for matching - it can lag
or word things differently than Torn's own company_type name for the same
id (seen firsthand: Torn calls type 12 "Oil Rig", Tornstats' own label for
that same block is "Oil Company"). The label is still surfaced for
human-readable diagnostics/warnings, just never used as the primary key.

If no company_type id is available at all (e.g. the profile call failed),
matching falls back to the label text, and failing that, to the older
heuristic: whichever block's position-name set is a superset of the
positions actually seen on your roster. Both fallbacks are logged back up
through compute_employee_rows' verification_note so a silent mismatch
doesn't happen - see EmployeeEfficiencyResult.verification_note.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from .tornstats_api import TornStatsAPI, TornStatsAPIError

NON_POSITION_KEYS = {"company", "stats", "status", "message"}

EMPLOYEE_HEADERS = [
    "tId", "name", "current_position", "wage", "days_in_company", "last_action_ts",
    "manual_labor", "intelligence", "endurance",
    "effectiveness_total", "effectiveness_working_stats", "effectiveness_settled_in",
    "effectiveness_director_education", "effectiveness_addiction",
    "effectiveness_inactivity", "effectiveness_management", "effectiveness_book",
    "effectiveness_merits",
    "projected_efficiency_current_position", "best_fit_position", "best_fit_efficiency",
    "assigned_position", "assigned_efficiency",
]


def find_company_type_block(
    efficiency_response: dict,
    known_position_names: set,
    expected_company_type_id: Optional[int] = None,
    expected_company_type_name: Optional[str] = None,
) -> Tuple[Optional[dict], str]:
    """Pick the block from a Tornstats /efficiency response that belongs to
    this company, trying progressively less-reliable signals:

      1. "id"        - efficiency_response[str(expected_company_type_id)],
                        matching Torn's own company_type id. Authoritative.
      2. "name"       - no id given/available; exact (case-insensitive)
                        match against block["company"]. Tornstats' label
                        text can differ from Torn's own type name for the
                        same id, so this is a weaker signal than #1.
      3. "heuristic"  - neither id nor name available/matched; whichever
                        block's position-name set is a superset of the
                        positions actually seen on the roster (smallest
                        such block, if several qualify). Pre-verification
                        behavior, kept as a last resort.
      4. "none"       - nothing matched at all.

    Returns (block_or_None, method) - method is always one of the four
    strings above, even when block is None, so callers can tell *why* a
    lookup failed/degraded instead of just that it did."""
    if expected_company_type_id is not None:
        block = efficiency_response.get(str(expected_company_type_id))
        if isinstance(block, dict) and "company" in block:
            return block, "id"

    if expected_company_type_name:
        wanted = expected_company_type_name.strip().lower()
        for key, block in efficiency_response.items():
            if key in NON_POSITION_KEYS or not isinstance(block, dict):
                continue
            if str(block.get("company", "")).strip().lower() == wanted:
                return block, "name"

    if known_position_names:
        best_block, best_size = None, None
        for key, block in efficiency_response.items():
            if key in NON_POSITION_KEYS or not isinstance(block, dict):
                continue
            position_names = set(block.keys()) - {"company"}
            if known_position_names.issubset(position_names):
                if best_size is None or len(position_names) < best_size:
                    best_block, best_size = block, len(position_names)
        if best_block is not None:
            return best_block, "heuristic"

    return None, "none"


def compute_employee_rows(
    employees: List[dict],
    tornstats: TornStatsAPI,
    expected_company_type_id: Optional[int] = None,
    expected_company_type_name: Optional[str] = None,
) -> Tuple[List[dict], List[str], str]:
    """
    employees: the "employees" list straight from TornAPI.get_company_employees()
    (v2 company/employees selection).

    expected_company_type_id / expected_company_type_name: this company's
    own type id/name from Torn's v2/company/profile ("type"."id"/"name"),
    if available - passed straight to find_company_type_block() for every
    employee lookup. Pass company_type_id whenever you have it; it's the
    only fully-verified match (see find_company_type_block's docstring).

    Returns (rows, position_names, verification_note):
      - rows: one flat dict per employee (EMPLOYEE_HEADERS fields, with
        assigned_position/assigned_efficiency defaulted to "" until/unless
        assign_positions() is run), plus a "projected" dict of
        {position_name: projected_efficiency} for GUI/assignment use (not
        one of EMPLOYEE_HEADERS).
      - position_names: sorted list of every position Tornstats reported
        for the matched company-type block, unioned across every employee
        that got a match. This is every position the company type offers -
        not just the ones currently staffed - so an empty seat (nobody's
        currently, say, an Inspector) still gets its own column instead of
        silently vanishing from the sheet. Falls back to the roster's own
        currently-held positions only if no block was ever matched at all.
      - verification_note: "" if every matched employee resolved via the
        authoritative company-type-id match; otherwise a short, human-
        readable warning describing what happened instead (fell back to
        name/heuristic matching for at least one employee, or Tornstats
        never returned a matching block at all) - surface this to the user
        rather than trusting the numbers silently.

    Calls Tornstats once per employee (their own man/int/end). Non-fatal
    per employee: if a call fails or no block match is found, that
    employee's projected fields are just left blank rather than aborting
    the whole run.
    """
    known_positions = {e.get("position", {}).get("name") for e in employees if e.get("position")}
    known_positions.discard(None)

    rows = []
    position_names_seen: Set[str] = set()
    match_methods: Set[str] = set()
    for emp in employees:
        stats = emp.get("stats", {}) or {}
        eff = emp.get("effectiveness", {}) or {}
        position = emp.get("position", {}) or {}
        position_name = position.get("name", "")
        last_action = emp.get("last_action", {})
        last_action_ts = last_action.get("timestamp", "") if isinstance(last_action, dict) else last_action

        projected: Dict[str, float] = {}
        try:
            resp = tornstats.get_efficiency(
                man=stats.get("manual_labor"),
                intel=stats.get("intelligence"),
                end=stats.get("endurance"),
            )
            block, method = find_company_type_block(
                resp, known_positions, expected_company_type_id, expected_company_type_name
            )
            match_methods.add(method)
            if block:
                projected = {k: v for k, v in block.items() if k != "company"}
                position_names_seen.update(projected.keys())
        except TornStatsAPIError:
            pass  # non-fatal - this employee just won't have projections this run
        except Exception:
            pass

        best_position, best_value = "", ""
        if projected:
            bp, bv = max(projected.items(), key=lambda kv: kv[1])
            best_position, best_value = bp, bv

        rows.append({
            "tId": emp.get("id"),
            "name": emp.get("name", ""),
            "current_position": position_name,
            "wage": emp.get("wage", 0),
            "days_in_company": emp.get("days_in_company", ""),
            "last_action_ts": last_action_ts,
            "manual_labor": stats.get("manual_labor", ""),
            "intelligence": stats.get("intelligence", ""),
            "endurance": stats.get("endurance", ""),
            "effectiveness_total": eff.get("total", 0),
            "effectiveness_working_stats": eff.get("working_stats", 0),
            "effectiveness_settled_in": eff.get("settled_in", 0),
            "effectiveness_director_education": eff.get("director_education", 0),
            "effectiveness_addiction": eff.get("addiction", 0),
            "effectiveness_inactivity": eff.get("inactivity", 0),
            "effectiveness_management": eff.get("management", 0),
            "effectiveness_book": eff.get("book", 0),
            "effectiveness_merits": eff.get("merits", 0),
            "projected_efficiency_current_position": projected.get(position_name, ""),
            "best_fit_position": best_position,
            "best_fit_efficiency": best_value,
            "assigned_position": "",
            "assigned_efficiency": "",
            "projected": projected,
        })

    if not match_methods or match_methods == {"none"}:
        verification_note = (
            "Tornstats never returned a company-type block for this company - "
            "position projections are empty. Check the company's Tornstats key."
        )
    elif match_methods == {"id"}:
        verification_note = ""
    else:
        fallbacks = sorted(m for m in match_methods if m not in ("id", "none"))
        verification_note = (
            "Position projections used a less-reliable fallback match "
            f"({', '.join(fallbacks) or 'none'}) for at least one employee instead of a "
            "verified company-type ID match - double check the company's Tornstats key "
            "belongs to this same company."
        )

    position_names = sorted(position_names_seen) if position_names_seen else sorted(known_positions)
    return rows, position_names, verification_note


def assign_positions(rows: List[dict], position_names: List[str],
                      position_capacities: Dict[str, int],
                      total_capacity: Optional[int] = None,
                      priority_order: Optional[List[str]] = None) -> None:
    """
    Fills positions in priority order - this is "Optimal Position
    (Priority)". priority_order lists positions top-to-bottom, highest
    priority first; any position_names missing from priority_order are
    processed afterward, in their default (alphabetical) order.

    For each position, in that order: among employees not yet assigned,
    rank by their projected efficiency *at that specific position* (highest
    first), and take up to that position's max headcount
    (position_capacities - a position absent from this dict is uncapped
    except by total_capacity). Once a position's seats are filled (or
    there's no capacity left at all, per total_capacity), move to the next
    position in priority order. An employee already assigned to a
    higher-priority position is no longer a candidate for later ones.

    This means a higher-priority position always gets first pick of the
    best remaining talent, even if a candidate would score higher at a
    lower-priority position - by design, since "priority" is meant to model
    staffing your most important seats first. Mutates `rows` in place,
    setting "assigned_position" / "assigned_efficiency" on every row ("" if
    the employee couldn't be placed - out of capacity, or no projection
    data for them at all).
    """
    ordered_positions = [p for p in (priority_order or []) if p in position_names]
    ordered_positions += [p for p in position_names if p not in ordered_positions]

    assigned_employee = [False] * len(rows)
    total_assigned = 0

    for pos in ordered_positions:
        if total_capacity is not None and total_assigned >= total_capacity:
            break
        cap = position_capacities.get(pos)

        candidates = []
        for idx, row in enumerate(rows):
            if assigned_employee[idx]:
                continue
            proj = row.get("projected") or {}
            if pos in proj:
                candidates.append((proj[pos], idx))
        candidates.sort(key=lambda c: c[0], reverse=True)

        filled_for_pos = 0
        for eff, idx in candidates:
            if cap is not None and filled_for_pos >= cap:
                break
            if total_capacity is not None and total_assigned >= total_capacity:
                break
            rows[idx]["assigned_position"] = pos
            rows[idx]["assigned_efficiency"] = eff
            assigned_employee[idx] = True
            filled_for_pos += 1
            total_assigned += 1

    for row in rows:
        row.setdefault("assigned_position", "")
        row.setdefault("assigned_efficiency", "")


def build_position_efficiency_rows(rows: List[dict], position_names: List[str]) -> Tuple[List[str], List[list]]:
    """Wide-format table: one row per employee, one column per position name
    seen on the roster, for the Position_Efficiency sheet tab."""
    headers = ["tId", "name", "current_position"] + position_names
    out = []
    for row in rows:
        projected = row.get("projected", {})
        out.append(
            [row["tId"], row["name"], row["current_position"]]
            + [projected.get(pos, "") for pos in position_names]
        )
    return headers, out
