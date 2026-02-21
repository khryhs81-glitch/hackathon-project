import argparse
import asyncio
import csv
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
IMPORTANT_DIR = BASE_DIR / "important_files"

try:
    from playwright.async_api import async_playwright
except Exception:  # pragma: no cover
    async_playwright = None  # type: ignore

JSONType = Union[Dict[str, Any], List[Any], str, int, float, bool, None]

# ----------------------------
# Heuristics to detect which JSON response contains the course "records"
# ----------------------------
LIKELY_RECORD_KEYS = {
    "crn",
    "courseReferenceNumber",
    "course_reference_number",
    "term_code",
    "termCode",
    "subject",
    "subjectCode",
    "course_number",
    "courseNumber",
    "number",
    "section",
    "section_number",
    "sectionNumber",
    "title",
    "courseTitle",
    "instructors",
    "faculty",
    "meetings",
    "meeting_patterns",
    "credit_hours",
    "credits",
    # seats-ish
    "maximumEnrollment",
    "enrollment",
    "seatsAvailable",
    "waitlistCount",
}

# ----------------------------
# Synonyms: key names to search for (deeply) in each record
# ----------------------------
SYNONYMS: Dict[str, List[str]] = {
    "term_code": ["term_code", "termCode", "term"],
    "crn": ["crn", "courseReferenceNumber", "course_reference_number"],
    "subject": ["subject", "subjectCode", "dept", "department", "departmentCode"],
    "course_number": ["course_number", "courseNumber", "number", "courseNum"],
    "section": ["section", "section_number", "sectionNumber", "sequenceNumber", "seq"],
    "title": ["title", "courseTitle", "course_title", "courseName", "name"],
    "credits": ["credits", "credit_hours", "creditHours"],

    "instructors": ["instructors", "faculty", "instructor", "instructor_list", "primaryInstructor"],
    "meetings": ["meetings", "meeting_patterns", "meetingPatterns", "schedule", "meetingTimes"],
    "notes": ["notes", "note", "specialNotes", "sectionNotes"],

    # Seats/capacity/enrollment (common key variants)
    "capacity": [
        "capacity",
        "maximumEnrollment",
        "maxEnrollment",
        "max_enrollment",
        "enrollmentMaximum",
        "enrollment_max",
        "seatCapacity",
        "seatsTotal",
        "seats_capacity",
        "totalSeats",
    ],
    "enrolled": [
        "enrolled",
        "enrollment",
        "actualEnrollment",
        "enrollmentActual",
        "enrollment_actual",
        "seatsTaken",
        "seats_filled",
        "filled",
        "totalEnrolled",
    ],
    "available": [
        "available",
        "seatsAvailable",
        "seats_available",
        "openSeats",
        "open_seats",
        "seatsRemaining",
        "seats_remaining",
        "remaining",
        "availableSeats",
    ],
    "waitlist_capacity": [
        "waitlistCapacity",
        "waitlist_capacity",
        "waitlistMaximum",
        "waitlistMax",
        "waitCapacity",
        "waitMax",
    ],
    "waitlist_count": [
        "waitlistCount",
        "waitlist_count",
        "waitCount",
        "waitlisted",
        "waitlist",
        "waitListCount",
    ],
}

# ----------------------------
# Helpers
# ----------------------------
def safe_json_dumps(x: Any) -> str:
    return json.dumps(x, ensure_ascii=False, separators=(",", ":"))

def sha1_of_obj(obj: Any) -> str:
    return hashlib.sha1(safe_json_dumps(obj).encode("utf-8")).hexdigest()

def deep_iter_lists(obj: JSONType, path: str = "$") -> Iterable[Tuple[str, List[Any]]]:
    """Yield (path, list) for all lists found in a nested JSON structure."""
    if isinstance(obj, list):
        yield (path, obj)
        for i, v in enumerate(obj):
            yield from deep_iter_lists(v, f"{path}[{i}]")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from deep_iter_lists(v, f"{path}.{k}")

def score_list_candidate(lst: List[Any]) -> float:
    """Score a list as 'likely course records'."""
    if not lst:
        return 0.0
    dict_elems = [x for x in lst[:50] if isinstance(x, dict)]
    if not dict_elems:
        return 0.0

    hits = 0
    for d in dict_elems[:10]:
        keys = set(d.keys())
        hits += sum(1 for k in LIKELY_RECORD_KEYS if k in keys)

    dict_ratio = len(dict_elems) / max(1, min(len(lst), 50))
    size_bonus = min(len(lst), 200) / 200.0  # 0..1

    return (hits * 1.0) + (dict_ratio * 10.0) + (size_bonus * 5.0)

def extract_best_records(payload: JSONType) -> Tuple[List[Dict[str, Any]], str, float]:
    """Find the best list-of-dicts inside payload and return (records, path, score)."""
    best: Tuple[List[Dict[str, Any]], str, float] = ([], "", 0.0)
    for path, lst in deep_iter_lists(payload):
        score = score_list_candidate(lst)
        if score <= best[2]:
            continue
        records = [x for x in lst if isinstance(x, dict)]
        if records:
            best = (records, path, score)
    return best

def set_query_param(url: str, key: str, value: Union[str, int]) -> str:
    p = urlparse(url)
    q = parse_qs(p.query, keep_blank_values=True)
    q[key] = [str(value)]
    new_query = urlencode(q, doseq=True)
    return urlunparse((p.scheme, p.netloc, p.path, p.params, new_query, p.fragment))

def try_set_offset_in_body(body_text: Optional[str], offset: int, limit: int, term_code: str) -> Optional[str]:
    """Best-effort update for JSON or form bodies used in POST requests."""
    if not body_text:
        return None

    # JSON body?
    try:
        obj = json.loads(body_text)
        if isinstance(obj, dict):
            for k in ["offset", "start", "from"]:
                if k in obj:
                    obj[k] = offset
            obj.setdefault("offset", offset)

            for k in ["limit", "pageSize", "size", "count"]:
                if k in obj:
                    obj[k] = limit
            obj.setdefault("limit", limit)

            for k in ["term_code", "termCode", "term"]:
                if k in obj:
                    obj[k] = term_code
            if "term_code" not in obj and "termCode" not in obj and "term" not in obj:
                obj["term_code"] = term_code

            return json.dumps(obj)
    except Exception:
        pass

    # form-encoded body?
    if "=" in body_text and "&" in body_text:
        parts = body_text.split("&")
        kv = {}
        for part in parts:
            if "=" in part:
                k, v = part.split("=", 1)
                kv[k] = v

        for k in ["offset", "start", "from"]:
            if k in kv:
                kv[k] = str(offset)
        kv.setdefault("offset", str(offset))

        for k in ["limit", "pageSize", "size", "count"]:
            if k in kv:
                kv[k] = str(limit)
        kv.setdefault("limit", str(limit))

        for k in ["term_code", "termCode", "term"]:
            if k in kv:
                kv[k] = term_code
        if "term_code" not in kv and "termCode" not in kv and "term" not in kv:
            kv["term_code"] = term_code

        return "&".join([f"{k}={v}" for k, v in kv.items()])

    return None

def to_int(x: Any) -> Optional[int]:
    try:
        if x is None:
            return None
        if isinstance(x, bool):
            return int(x)
        if isinstance(x, (int, float)):
            return int(x)
        s = str(x).strip()
        if s == "":
            return None
        return int(float(s))
    except Exception:
        return None

def deep_find_first(obj: Any, target_keys: set) -> Any:
    """Return the first value found whose dict key is in target_keys."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in target_keys:
                return v
            found = deep_find_first(v, target_keys)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = deep_find_first(v, target_keys)
            if found is not None:
                return found
    return None

def deep_pick_any(obj: Any, keys: List[str]) -> Any:
    """Try keys directly if dict, else deep search anywhere in obj."""
    if isinstance(obj, dict):
        for k in keys:
            if k in obj:
                return obj[k]
    return deep_find_first(obj, set(keys))

# ----------------------------
# Seat ratio extraction (e.g. "23/25") anywhere in the record
# ----------------------------
SEAT_RATIO_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*$")

def deep_find_seat_ratio(obj: Any) -> Optional[Tuple[int, int]]:
    """
    Search the entire record for a string like '23/25'.
    Returns (enrolled, capacity) if found.
    """
    if isinstance(obj, str):
        m = SEAT_RATIO_RE.match(obj)
        if m:
            return (int(m.group(1)), int(m.group(2)))
        return None

    if isinstance(obj, dict):
        seatish_keys = ("seat", "enroll", "cap", "avail", "remain", "wait")
        for k, v in obj.items():
            if any(s in str(k).lower() for s in seatish_keys):
                found = deep_find_seat_ratio(v)
                if found:
                    return found
        for v in obj.values():
            found = deep_find_seat_ratio(v)
            if found:
                return found
        return None

    if isinstance(obj, list):
        for v in obj:
            found = deep_find_seat_ratio(v)
            if found:
                return found
        return None

    return None

def normalize_record(rec: Dict[str, Any]) -> Dict[str, Any]:
    """
    Schema-agnostic normalization:
    - Deeply searches for capacity/enrolled/available using SYNONYMS.
    - If capacity/enrolled are missing, tries to find a '23/25' seat ratio anywhere.
    - seats_remaining (open seats) = available if present else capacity - enrolled.
    """
    def get_field(name: str) -> Any:
        return deep_pick_any(rec, SYNONYMS[name])

    instructors = get_field("instructors")
    if isinstance(instructors, dict):
        instructors = [instructors]
    if isinstance(instructors, str):
        instructors = [instructors]

    capacity_i = to_int(get_field("capacity"))
    enrolled_i = to_int(get_field("enrolled"))
    available_i = to_int(get_field("available"))

    if capacity_i is None or enrolled_i is None:
        ratio = deep_find_seat_ratio(rec)
        if ratio:
            enrolled_i, capacity_i = ratio

    seats_remaining_i = None
    if available_i is not None:
        seats_remaining_i = available_i
    elif capacity_i is not None and enrolled_i is not None:
        seats_remaining_i = capacity_i - enrolled_i

    wait_cap_i = to_int(get_field("waitlist_capacity"))
    wait_cnt_i = to_int(get_field("waitlist_count"))

    return {
        "term_code": get_field("term_code"),
        "crn": get_field("crn"),
        "subject": get_field("subject"),
        "course_number": get_field("course_number"),
        "section": get_field("section"),
        "title": get_field("title"),
        "credits": get_field("credits"),

        "capacity": capacity_i,
        "enrolled": enrolled_i,
        "seats_remaining": seats_remaining_i,
        "waitlist_capacity": wait_cap_i,
        "waitlist_count": wait_cnt_i,

        "instructors": instructors,
        "meetings": get_field("meetings"),
        "notes": get_field("notes"),
    }

def flatten_for_csv(row: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for k, v in row.items():
        if v is None:
            out[k] = ""
        elif isinstance(v, (str, int, float, bool)):
            out[k] = str(v)
        elif isinstance(v, list) and all(isinstance(x, (str, int, float, bool)) for x in v):
            out[k] = "; ".join(map(str, v))
        else:
            out[k] = safe_json_dumps(v)
    return out

def stable_record_id(rec: Dict[str, Any]) -> str:
    for k in ["crn", "courseReferenceNumber", "course_reference_number"]:
        if k in rec and rec[k] is not None:
            return f"crn:{rec[k]}"
    return f"sha1:{sha1_of_obj(rec)}"

# ----------------------------
# Discovery: find which JSON response contains records
# ----------------------------
@dataclass
class DiscoveredRequest:
    method: str
    url: str
    headers: Dict[str, str]
    post_data: Optional[str]
    records_path: str
    records_score: float

async def discover_data_request(page, schedule_url: str, wait_ms: int = 10000) -> Tuple[DiscoveredRequest, List[Dict[str, Any]]]:
    best_req: Optional[DiscoveredRequest] = None
    best_records: List[Dict[str, Any]] = []

    async def on_response(resp):
        nonlocal best_req, best_records
        try:
            ct = (resp.headers or {}).get("content-type", "")
            is_jsonish = "application/json" in ct.lower()

            if is_jsonish:
                payload = await resp.json()
            else:
                text = await resp.text()
                if not text:
                    return
                t = text.lstrip()
                if not (t.startswith("{") or t.startswith("[")):
                    return
                payload = json.loads(text)

            records, path, score = extract_best_records(payload)
            if not records or score <= 0:
                return

            req = resp.request
            method = req.method.upper()
            url = resp.url
            headers = dict(req.headers)
            post_data = await req.post_data() if method in {"POST", "PUT"} else None

            should_replace = False
            if best_req is None:
                should_replace = True
            else:
                if score > best_req.records_score:
                    should_replace = True
                elif abs(score - best_req.records_score) < 1e-6 and len(records) > len(best_records):
                    should_replace = True

            if should_replace:
                best_req = DiscoveredRequest(
                    method=method,
                    url=url,
                    headers=headers,
                    post_data=post_data,
                    records_path=path,
                    records_score=score,
                )
                best_records = records
        except Exception:
            return

    page.on("response", on_response)

    await page.goto(schedule_url, wait_until="domcontentloaded")
    await page.wait_for_timeout(wait_ms)

    if best_req is None or not best_records:
        raise RuntimeError(
            "Could not auto-detect the JSON response containing course records. "
            "Try increasing --discover-wait or run without --headless to verify the page loads."
        )

    return best_req, best_records

async def fetch_records_via_discovered_request(
    request_ctx,
    discovered: DiscoveredRequest,
    term_code: str,
    offset: int,
    limit: int,
) -> List[Dict[str, Any]]:
    method = discovered.method.upper()
    url = discovered.url

    url = set_query_param(url, "term_code", term_code)
    url = set_query_param(url, "offset", offset)
    url = set_query_param(url, "limit", limit)

    headers = dict(discovered.headers)
    headers.setdefault("accept", "application/json,text/plain,*/*")

    body = None
    if method in {"POST", "PUT"}:
        body = try_set_offset_in_body(discovered.post_data, offset=offset, limit=limit, term_code=term_code)

    resp = await request_ctx.fetch(url, method=method, headers=headers, data=body)
    if not resp.ok:
        raise RuntimeError(f"Request failed: {method} {url} -> HTTP {resp.status}")

    try:
        payload = await resp.json()
    except Exception:
        text = await resp.text()
        payload = json.loads(text)

    records, _, _ = extract_best_records(payload)
    return records

# ----------------------------
# Main run
# ----------------------------
async def run(
    term_code: str,
    limit: int,
    out_prefix: str,
    headless: bool,
    discover_wait: int,
    test_seats_available: Optional[int] = None,  # NEW
):
    if async_playwright is None:
        raise RuntimeError(
            "playwright is not installed. Install it (and run playwright install) to use this scraper."
        )
    schedule_url = f"https://course-schedule.davidson.edu/#/schedule?limit={limit}&offset=0&term_code={term_code}"

    prefix = Path(out_prefix)
    out_dir = prefix.parent
    base = prefix.name
    if str(out_dir) == ".":
        out_dir = Path(".")
    out_dir.mkdir(parents=True, exist_ok=True)

    raw_path = out_dir / f"{base}_raw.jsonl"
    norm_path = out_dir / f"{base}_normalized.jsonl"
    csv_path = out_dir / f"{base}_normalized.csv"

    seen_ids = set()
    total = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context()
        page = await context.new_page()

        discovered, first_records = await discover_data_request(page, schedule_url, wait_ms=discover_wait)

        print("Discovered data request:")
        print(f"  method: {discovered.method}")
        print(f"  url:    {discovered.url}")
        print(f"  path:   {discovered.records_path}")
        print(f"  score:  {discovered.records_score:.2f}")
        print(f"  first page records: {len(first_records)}")

        csv_file = csv_path.open("w", newline="", encoding="utf-8")
        csv_writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "term_code",
                "crn",
                "subject",
                "course_number",
                "section",
                "title",
                "credits",
                "capacity",
                "enrolled",
                "seats_remaining",
                "waitlist_capacity",
                "waitlist_count",
                "instructors",
                "meetings",
                "notes",
            ],
            extrasaction="ignore",
        )
        csv_writer.writeheader()

        with raw_path.open("w", encoding="utf-8") as f_raw, norm_path.open("w", encoding="utf-8") as f_norm:

            def write_record(rec: Dict[str, Any]):
                nonlocal total
                rid = stable_record_id(rec)
                if rid in seen_ids:
                    return
                seen_ids.add(rid)
                total += 1

                f_raw.write(safe_json_dumps(rec) + "\n")

                norm = normalize_record(rec)

                # TEST OVERRIDE: force available seats for every record
                if test_seats_available is not None:
                    norm["seats_remaining"] = int(test_seats_available)

                f_norm.write(safe_json_dumps(norm) + "\n")
                csv_writer.writerow(flatten_for_csv(norm))

            for r in first_records:
                write_record(r)

            offset = limit
            empty_pages_in_a_row = 0

            while True:
                records = await fetch_records_via_discovered_request(
                    request_ctx=context.request,
                    discovered=discovered,
                    term_code=term_code,
                    offset=offset,
                    limit=limit,
                )

                if not records:
                    empty_pages_in_a_row += 1
                    if empty_pages_in_a_row >= 2:
                        break
                else:
                    empty_pages_in_a_row = 0
                    before = len(seen_ids)
                    for r in records:
                        write_record(r)
                    after = len(seen_ids)
                    if after == before:
                        break

                offset += limit

        csv_file.close()
        await browser.close()

    print(f"Done. Saved {total} unique records:")
    print(f"  {raw_path}")
    print(f"  {norm_path}")
    print(f"  {csv_path}")

def main():
    ap = argparse.ArgumentParser(description="Scrape Davidson course schedule and export CSV with seats/capacity.")
    ap.add_argument("--term", default="202502", help="Term code (default: 202502)")
    ap.add_argument("--limit", type=int, default=50, help="Page size (default: 50)")
    ap.add_argument("--out", default=str(IMPORTANT_DIR / "davidson_courses"), help="Output prefix (default: important_files/davidson_courses)")
    ap.add_argument("--headless", action="store_true", help="Run headless")
    ap.add_argument("--discover-wait", type=int, default=10000, help="ms to wait during discovery (default: 10000)")

    # NEW: testing flag
    ap.add_argument(
        "--test-seats-available",
        type=int,
        default=25,
        help="FOR TESTING ONLY: force seats_remaining (available seats) to this value for every record",
    )

    args = ap.parse_args()

    asyncio.run(
        run(
            term_code=args.term,
            limit=args.limit,
            out_prefix=args.out,
            headless=args.headless,
            discover_wait=args.discover_wait,
            test_seats_available=args.test_seats_available,
        )
    )

if __name__ == "__main__":
    main()