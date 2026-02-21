import argparse
import asyncio
import csv
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from playwright.async_api import async_playwright

JSONType = Union[Dict[str, Any], List[Any], str, int, float, bool, None]

# Heuristic keys commonly present in course/section records
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
}

# For normalized output (best-effort; schema-agnostic)
SYNONYMS = {
    "term_code": ["term_code", "termCode", "term"],
    "crn": ["crn", "courseReferenceNumber", "course_reference_number"],
    "subject": ["subject", "subjectCode", "dept", "department"],
    "course_number": ["course_number", "courseNumber", "number"],
    "section": ["section", "section_number", "sectionNumber"],
    "title": ["title", "courseTitle", "course_title", "courseName", "name"],
    "credits": ["credits", "credit_hours", "creditHours"],
    "instructors": ["instructors", "faculty", "instructor", "instructor_list"],
    "meetings": ["meetings", "meeting_patterns", "meetingPatterns", "schedule"],
    "notes": ["notes", "note"],
}

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

    # Count key hits across sample dicts
    hits = 0
    for d in dict_elems[:10]:
        keys = set(d.keys())
        hits += sum(1 for k in LIKELY_RECORD_KEYS if k in keys)

    # Prefer lists that are mostly dicts and not tiny
    dict_ratio = len(dict_elems) / max(1, min(len(lst), 50))
    size_bonus = min(len(lst), 200) / 200.0  # 0..1

    return (hits * 1.0) + (dict_ratio * 10.0) + (size_bonus * 5.0)

def extract_best_records(payload: JSONType) -> Tuple[List[Dict[str, Any]], str, float]:
    """
    Find the 'best' list-of-dicts inside a JSON payload and return (records, path, score).
    """
    best: Tuple[List[Dict[str, Any]], str, float] = ([], "", 0.0)
    for path, lst in deep_iter_lists(payload):
        score = score_list_candidate(lst)
        if score <= best[2]:
            continue
        # Convert to list[dict] safely
        records = [x for x in lst if isinstance(x, dict)]
        if not records:
            continue
        best = (records, path, score)
    return best

def set_query_param(url: str, key: str, value: Union[str, int]) -> str:
    p = urlparse(url)
    q = parse_qs(p.query, keep_blank_values=True)
    q[key] = [str(value)]
    new_query = urlencode(q, doseq=True)
    return urlunparse((p.scheme, p.netloc, p.path, p.params, new_query, p.fragment))

def try_set_offset_in_body(body_text: Optional[str], offset: int, limit: int, term_code: str) -> Optional[str]:
    """
    Best-effort update for JSON POST bodies:
    - If body is JSON, set offset/limit/term_code keys when present or add them.
    - If body is form-encoded, update fields similarly.
    """
    if not body_text:
        return None

    # JSON body?
    try:
        obj = json.loads(body_text)
        if isinstance(obj, dict):
            # Common names
            for k in ["offset", "start", "from"]:
                if k in obj:
                    obj[k] = offset
            if "offset" not in obj:
                obj["offset"] = offset

            for k in ["limit", "pageSize", "size", "count"]:
                if k in obj:
                    obj[k] = limit
            if "limit" not in obj:
                obj["limit"] = limit

            for k in ["term_code", "termCode", "term"]:
                if k in obj:
                    obj[k] = term_code
            if "term_code" not in obj and "termCode" not in obj and "term" not in obj:
                obj["term_code"] = term_code

            return json.dumps(obj)
    except Exception:
        pass

    # Form-encoded? (offset=...&limit=...)
    if "=" in body_text and "&" in body_text:
        parts = body_text.split("&")
        kv = {}
        for part in parts:
            if "=" in part:
                k, v = part.split("=", 1)
                kv[k] = v
        # update common fields
        for k in ["offset", "start", "from"]:
            if k in kv:
                kv[k] = str(offset)
        if "offset" not in kv:
            kv["offset"] = str(offset)

        for k in ["limit", "pageSize", "size", "count"]:
            if k in kv:
                kv[k] = str(limit)
        if "limit" not in kv:
            kv["limit"] = str(limit)

        for k in ["term_code", "termCode", "term"]:
            if k in kv:
                kv[k] = term_code
        if "term_code" not in kv and "termCode" not in kv and "term" not in kv:
            kv["term_code"] = term_code

        return "&".join([f"{k}={v}" for k, v in kv.items()])

    return None

def pick_any(d: Dict[str, Any], keys: List[str]) -> Any:
    for k in keys:
        if k in d:
            return d[k]
    return None

def normalize_record(rec: Dict[str, Any]) -> Dict[str, Any]:
    # Try top-level first, then look one level down in common containers
    containers = [rec]
    for container_key in ["course", "section", "schedule", "data"]:
        v = rec.get(container_key)
        if isinstance(v, dict):
            containers.append(v)

    def get_field(field: str) -> Any:
        for c in containers:
            val = pick_any(c, SYNONYMS[field])
            if val is not None:
                return val
        return None

    instructors = get_field("instructors")
    if isinstance(instructors, dict):
        instructors = [instructors]
    if isinstance(instructors, str):
        instructors = [instructors]

    return {
        "term_code": get_field("term_code"),
        "crn": get_field("crn"),
        "subject": get_field("subject"),
        "course_number": get_field("course_number"),
        "section": get_field("section"),
        "title": get_field("title"),
        "credits": get_field("credits"),
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

@dataclass
class DiscoveredRequest:
    method: str
    url: str
    headers: Dict[str, str]
    post_data: Optional[str]  # raw text, maybe JSON
    records_path: str
    records_score: float

async def discover_data_request(page, schedule_url: str, wait_ms: int = 6000) -> Tuple[DiscoveredRequest, List[Dict[str, Any]]]:
    """
    Load the schedule UI and watch JSON responses.
    Choose the response whose JSON contains the best-scoring list-of-dicts.
    """
    best_req: Optional[DiscoveredRequest] = None
    best_records: List[Dict[str, Any]] = []

    async def on_response(resp):
        nonlocal best_req, best_records
        try:
            ct = (resp.headers or {}).get("content-type", "")
            # Some servers omit content-type; still try if response text looks like JSON
            is_jsonish = "application/json" in ct.lower()

            payload: Any
            if is_jsonish:
                payload = await resp.json()
            else:
                text = await resp.text()
                if not text or len(text) < 2:
                    return
                if not (text.lstrip().startswith("{") or text.lstrip().startswith("[")):
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

            # Prefer the best score; tie-break on record count
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
            "Could not auto-detect the JSON response that contains course records. "
            "Try increasing --discover-wait (ms) or run headed (no --headless) and ensure the page loads."
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
    # Update query params if present/needed
    url = set_query_param(url, "term_code", term_code)
    url = set_query_param(url, "offset", offset)
    url = set_query_param(url, "limit", limit)

    headers = dict(discovered.headers)
    # Make sure we accept JSON
    headers.setdefault("accept", "application/json,text/plain,*/*")

    body = None
    if method in {"POST", "PUT"}:
        body = try_set_offset_in_body(discovered.post_data, offset=offset, limit=limit, term_code=term_code)

    # Use Playwright's request API (fast; no page reload)
    resp = await request_ctx.fetch(url, method=method, headers=headers, data=body)
    if not resp.ok:
        raise RuntimeError(f"Request failed: {method} {url} -> {resp.status}")

    # Parse JSON (fallback to text->json)
    try:
        payload = await resp.json()
    except Exception:
        text = await resp.text()
        payload = json.loads(text)

    records, _, _ = extract_best_records(payload)
    return records

def stable_record_id(rec: Dict[str, Any]) -> str:
    # Prefer CRN if present; otherwise hash the object
    for k in ["crn", "courseReferenceNumber", "course_reference_number"]:
        if k in rec and rec[k] is not None:
            return f"crn:{rec[k]}"
    return f"sha1:{sha1_of_obj(rec)}"

async def run(term_code: str, limit: int, out_prefix: str, headless: bool, discover_wait: int):
    schedule_url = f"https://course-schedule.davidson.edu/#/schedule?limit={limit}&offset=0&term_code={term_code}"

    raw_path = f"{out_prefix}_raw.jsonl"
    norm_path = f"{out_prefix}_normalized.jsonl"
    csv_path = f"{out_prefix}_normalized.csv"

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

        # Prepare CSV writer
        csv_file = open(csv_path, "w", newline="", encoding="utf-8")
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
                "instructors",
                "meetings",
                "notes",
            ],
        )
        csv_writer.writeheader()

        with open(raw_path, "w", encoding="utf-8") as f_raw, open(norm_path, "w", encoding="utf-8") as f_norm:
            # Helper to write records
            def write_record(rec: Dict[str, Any]):
                nonlocal total
                rid = stable_record_id(rec)
                if rid in seen_ids:
                    return
                seen_ids.add(rid)
                total += 1

                f_raw.write(safe_json_dumps(rec) + "\n")

                norm = normalize_record(rec)
                f_norm.write(safe_json_dumps(norm) + "\n")
                csv_writer.writerow(flatten_for_csv(norm))

            # Write first page from discovery
            for r in first_records:
                write_record(r)

            # Now paginate using the discovered request template
            offset = limit  # we already got offset=0
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
                    # Some backends may return empty once before finalizing; allow one retry.
                    if empty_pages_in_a_row >= 2:
                        break
                else:
                    empty_pages_in_a_row = 0
                    before = len(seen_ids)
                    for r in records:
                        write_record(r)
                    after = len(seen_ids)

                    # Stop if we got no new unique records (safety against infinite loops)
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
    ap = argparse.ArgumentParser(description="Scrape Davidson course schedule via Playwright (Option B).")
    ap.add_argument("--term", default="202502", help="Term code (default: 202502)")
    ap.add_argument("--limit", type=int, default=50, help="Page size (default: 50)")
    ap.add_argument("--out", default="davidson_courses", help="Output prefix (default: davidson_courses)")
    ap.add_argument("--headless", action="store_true", help="Run browser headless")
    ap.add_argument("--discover-wait", type=int, default=7000, help="ms to wait for JSON responses during discovery (default: 7000)")
    args = ap.parse_args()

    asyncio.run(
        run(
            term_code=args.term,
            limit=args.limit,
            out_prefix=args.out,
            headless=args.headless,
            discover_wait=args.discover_wait,
        )
    )

if __name__ == "__main__":
    main()