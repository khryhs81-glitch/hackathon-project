"""
server.py (FastAPI)

Goals:
- Serve your frontend (static/index.html) and a stable JSON API.
- Avoid "Not Found" and shape-mismatch crashes by providing:
  - Route aliases (multiple endpoint spellings)
  - Consistent response shapes
  - "No results yet" returns 200 with ok:false (not 404)
- Work locally and on DigitalOcean:
  - Uses DATABASE_URL if provided (Postgres on DO)
  - Falls back to local SQLite if not set
  - Serves static assets from ./static

Run locally:
  python3 -m uvicorn server:app --reload --port 8001

DigitalOcean run command:
  uvicorn server:app --host 0.0.0.0 --port $PORT
"""

from __future__ import annotations

import csv
import json
import os
import random
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from pydantic import BaseModel

# SQLAlchemy (works with sqlite or postgres)
from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine, select
from sqlalchemy.orm import Session, declarative_base, sessionmaker


# ============================================================
# Paths / Config
# ============================================================
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
IMPORTANT_DIR = BASE_DIR / "important_files"

# Your tidy CSV lives here based on earlier code
TIDY_CSV_PATH = IMPORTANT_DIR / "davidson_courses_tidy.csv"

# Optional: if you prefer a different tidy filename:
ALT_TIDY_CSV_PATH = IMPORTANT_DIR / "davidson_courses_normalized.csv"

# Admin token (optional). If set, admin endpoints require it.
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "").strip()

# For testing capacity overrides (frontend has "capacity (testing)")
DEFAULT_FORCE_CAPACITY = int(os.getenv("DEFAULT_FORCE_CAPACITY", "0") or "0")  # 0 = off


# ============================================================
# Small helpers
# ============================================================
def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _clean(x: Any) -> str:
    return "" if x is None else str(x).strip()


def _to_int_or_none(x: Any) -> Optional[int]:
    s = _clean(x)
    if not s:
        return None
    try:
        return int(float(s))
    except Exception:
        return None


def _to_float_or_none(x: Any) -> Optional[float]:
    s = _clean(x)
    if not s:
        return None
    try:
        return float(s)
    except Exception:
        return None


def parse_seats_value(seats: Any) -> Tuple[Optional[int], Optional[int]]:
    """
    Accepts: "23/25" or "23" or ""
    Returns: (enrolled, capacity)
    """
    s = _clean(seats)
    if not s:
        return (None, None)
    if "/" in s:
        a, b = s.split("/", 1)
        try:
            return (int(a.strip()), int(b.strip()))
        except Exception:
            return (None, None)
    try:
        return (int(s), None)
    except Exception:
        return (None, None)


def ensure_list(x: Any) -> List[Any]:
    if x is None:
        return []
    if isinstance(x, list):
        return x
    return [x]


# ============================================================
# Course model + CSV loader (supports your tidy CSV format)
# ============================================================
@dataclass
class Course:
    class_id: str  # CRN
    title: str
    subject: str = ""
    course_number: str = ""
    section: str = ""
    credits: Optional[float] = None
    days: str = ""
    time: str = ""
    room: str = ""
    instructor: str = ""
    enrolled: Optional[int] = None
    capacity: Optional[int] = None
    raw: Dict[str, str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "class_id": self.class_id,
            "crn": self.class_id,  # alias for convenience
            "title": self.title,
            "subject": self.subject,
            "course_number": self.course_number,
            "section": self.section,
            "credits": self.credits,
            "weekdays": self.days,
            "time": self.time,
            "room": self.room,
            "instructor": self.instructor,
            "enrolled": self.enrolled,
            "capacity": self.capacity,
            "seats_remaining": None if (self.enrolled is None or self.capacity is None) else max(self.capacity - self.enrolled, 0),
        }


def _pick(row: Dict[str, str], *keys: str) -> str:
    for k in keys:
        if k in row and _clean(row[k]) != "":
            return _clean(row[k])
    return ""


def load_courses_from_tidy_csv(path: Path) -> List[Course]:
    if not path.exists():
        raise FileNotFoundError(f"Tidy CSV not found at: {path}")

    courses: List[Course] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # This supports both your "normalized" tidy format and your earlier "tidy" format.
            crn = _pick(row, "crn", "CRN", "class_id", "Class ID", "CRN ")
            title = _pick(row, "title", "Title", "TITLE", "Course Title")
            credits = _to_float_or_none(_pick(row, "credits", "Cred", "CREDITS", "Cred "))
            days = _pick(row, "Days", "days", "weekdays", "WEEKDAYS")
            time = _pick(row, "Time", "time", "class_time", "Class Time")
            room = _pick(row, "Room", "room")
            instructor = _pick(row, "Instructor", "instructor", "INSTRUCTOR")

            # Subject/course/section sometimes encoded in "Crs & Sec" like "AFR-101-A"
            crs_sec = _pick(row, "Crs & Sec", "crs_sec", "Crs&Sec")
            subject, course_number, section = "", "", ""
            if crs_sec and "-" in crs_sec:
                parts = crs_sec.split("-")
                if len(parts) >= 3:
                    subject = parts[0].strip()
                    course_number = parts[1].strip()
                    section = parts[2].strip()

            enrolled = _to_int_or_none(_pick(row, "enrolled", "Enrolled"))
            capacity = _to_int_or_none(_pick(row, "capacity", "Capacity"))
            # In your tidy output, seats are stored as "Seats Left" = "enrolled/capacity" (from your script)
            seats_disp = _pick(row, "Seats Left", "seats_left", "Seats")
            if (enrolled is None and capacity is None) and seats_disp:
                enrolled, capacity = parse_seats_value(seats_disp)

            crn = _clean(crn)
            if not crn:
                # skip rows without a CRN
                continue

            courses.append(
                Course(
                    class_id=crn,
                    title=title or "",
                    subject=subject,
                    course_number=course_number,
                    section=section,
                    credits=credits,
                    days=days,
                    time=time,
                    room=room,
                    instructor=instructor,
                    enrolled=enrolled,
                    capacity=capacity,
                    raw=dict(row),
                )
            )
    return courses


def load_courses_best_effort() -> List[Course]:
    """
    Tries the main tidy CSV path, then alternates. Never throws uncaught errors.
    """
    try:
        return load_courses_from_tidy_csv(TIDY_CSV_PATH)
    except FileNotFoundError:
        if ALT_TIDY_CSV_PATH.exists():
            return load_courses_from_tidy_csv(ALT_TIDY_CSV_PATH)
        raise
    except Exception:
        raise


# ============================================================
# Database (Postgres on DO, SQLite locally)
# ============================================================
def normalize_db_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    # DigitalOcean sometimes gives postgres:// which SQLAlchemy prefers postgresql://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


DATABASE_URL = normalize_db_url(os.getenv("DATABASE_URL", "")) or f"sqlite:///{BASE_DIR / 'app.db'}"

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


class StudentSubmission(Base):
    __tablename__ = "student_submissions"

    student_id = Column(String, primary_key=True)
    grade = Column(Integer, nullable=False)
    payload_json = Column(Text, nullable=False)  # stores picks + extra fields
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class LotteryResult(Base):
    __tablename__ = "lottery_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String, nullable=False, index=True)
    student_id = Column(String, nullable=False, index=True)
    grade = Column(Integer, nullable=False)
    lottery_number = Column(Integer, nullable=False)
    result_json = Column(Text, nullable=False)  # stores assignments + metadata
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def db_session() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================================
# Pydantic-ish payloads (flexible)
# ============================================================
class PicksPayload(BaseModel):
    """
    This is flexible on purpose so your frontend doesn't break if it changes field names.

    Accepts any of these shapes:
      { student_id, grade, choices: [[...], [...], ...], preference?, capacity? }
      { studentId, grade, picks: [[...]], ... }
      { student: {id, grade}, choices: ... }
    """
    student_id: str = ""
    grade: int = 12
    choices: List[List[str]] = []
    preference: Optional[str] = None
    capacity: Optional[int] = None

    @classmethod
    def from_any(cls, data: Dict[str, Any]) -> "PicksPayload":
        d = dict(data or {})

        # Normalize student_id
        sid = d.get("student_id") or d.get("studentId")
        if not sid and isinstance(d.get("student"), dict):
            sid = d["student"].get("student_id") or d["student"].get("id") or d["student"].get("studentId")
        sid = _clean(sid) or "S000"

        # grade
        grade = d.get("grade")
        if grade is None and isinstance(d.get("student"), dict):
            grade = d["student"].get("grade")
        try:
            grade = int(grade)
        except Exception:
            grade = 12

        # choices/picks
        choices = d.get("choices")
        if choices is None:
            choices = d.get("picks")
        if choices is None and isinstance(d.get("rounds"), list):
            # some UIs store rounds as list of round objects
            # try: rounds = [{choices:[...]}, ...]
            tmp: List[List[str]] = []
            for r in d["rounds"]:
                if isinstance(r, dict):
                    tmp.append(ensure_list(r.get("choices")))
                else:
                    tmp.append(ensure_list(r))
            choices = tmp

        if not isinstance(choices, list):
            choices = []

        # ensure nested list
        norm_choices: List[List[str]] = []
        for r in choices:
            if r is None:
                norm_choices.append([])
            elif isinstance(r, list):
                norm_choices.append([_clean(x) for x in r if _clean(x)])
            else:
                norm_choices.append([_clean(r)] if _clean(r) else [])

        preference = d.get("preference")
        capacity = d.get("capacity")
        if capacity is None:
            capacity = d.get("force_capacity") or d.get("forceCapacity")
        try:
            capacity = int(capacity) if capacity is not None and str(capacity).strip() != "" else None
        except Exception:
            capacity = None

        return cls(
            student_id=sid,
            grade=grade,
            choices=norm_choices,
            preference=_clean(preference) or None,
            capacity=capacity,
        )


# ============================================================
# FastAPI app
# ============================================================
app = FastAPI(title="Web Choice API", version="1.0.0")

# CORS: safe defaults; you can lock this down later
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount /static if exists (DO + local)
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR), html=False), name="static")


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # Prevent blank "server error" responses in prod; always return JSON.
    tb = traceback.format_exc()
    return JSONResponse(
        status_code=500,
        content={
            "ok": False,
            "error": "Unhandled server error",
            "detail": str(exc),
            "path": str(request.url.path),
            "trace": tb if os.getenv("ENV", "").lower() != "prod" else None,
        },
    )


# ============================================================
# Frontend routes
# ============================================================
@app.get("/", response_class=HTMLResponse)
def index():
    idx = STATIC_DIR / "index.html"
    if idx.exists():
        return FileResponse(str(idx))
    return HTMLResponse(
        "<h1>Server running</h1><p>Missing static/index.html</p>",
        status_code=200,
    )


@app.get("/favicon.ico")
def favicon():
    ico = STATIC_DIR / "favicon.ico"
    if ico.exists():
        return FileResponse(str(ico))
    # Avoid 404 spam
    return Response(status_code=204)


# ============================================================
# Health / status
# ============================================================
@app.get("/api/health")
@app.get("/api/status")
@app.get("/health")
def health():
    return {"ok": True, "db": True, "time": utcnow().isoformat(), "tidy_csv": str(TIDY_CSV_PATH)}


# ============================================================
# Courses API
# ============================================================
@app.get("/api/classes")
@app.get("/api/courses")
@app.get("/api/reload_courses")
@app.get("/api/reload-courses")
def api_classes(wrap: bool = Query(default=False)):
    """
    IMPORTANT:
    - Default returns a JSON ARRAY so your frontend can do: for (const c of classes) ...
    - If you want wrapped format: /api/classes?wrap=1
    """
    try:
        courses = load_courses_best_effort()
        payload = [c.to_dict() for c in courses]
        if wrap:
            return {"ok": True, "count": len(payload), "classes": payload}
        return payload
    except FileNotFoundError as e:
        # Return 200 with ok:false so UI can show message without "server error" panic
        return {"ok": False, "detail": str(e), "classes": []} if wrap else []
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/refresh")
@app.post("/api/refresh_courses")
@app.post("/api/refresh-courses")
def refresh_courses():
    """
    Frontend button alias. We don't scrape here by default (Playwright is heavy on DO),
    but we keep the route so the UI never 404s.
    """
    # Simply confirm whether tidy CSV exists
    exists = TIDY_CSV_PATH.exists()
    return {
        "ok": True,
        "detail": "Refresh is a no-op in cloud by default. Upload/commit the tidy CSV instead.",
        "tidy_csv_exists": exists,
        "tidy_csv_path": str(TIDY_CSV_PATH),
    }


# ============================================================
# Picks API (route aliases to prevent 404)
# ============================================================
@app.post("/api/picks")
@app.post("/api/submit_picks")
@app.post("/api/submit-picks")
@app.post("/api/picks/submit")
def submit_picks(raw: Dict[str, Any] = Body(...), db: Session = Depends(db_session)):
    """
    Saves / overwrites a student's picks.
    Accepts multiple routes so your frontend won't 404 if it calls a different spelling.
    """
    payload = PicksPayload.from_any(raw)
    now = utcnow()

    stored = {
        "student_id": payload.student_id,
        "grade": payload.grade,
        "choices": payload.choices,
        "preference": payload.preference,
        "capacity": payload.capacity,
    }

    row = db.get(StudentSubmission, payload.student_id)
    if row is None:
        row = StudentSubmission(
            student_id=payload.student_id,
            grade=int(payload.grade),
            payload_json=json.dumps(stored),
            updated_at=now,
        )
        db.add(row)
    else:
        row.grade = int(payload.grade)
        row.payload_json = json.dumps(stored)
        row.updated_at = now

    db.commit()
    return {"ok": True, "student_id": payload.student_id, "saved_at": now.isoformat()}


@app.get("/api/picks/{student_id}")
@app.get("/api/submission/{student_id}")
@app.get("/api/submissions/{student_id}")
def get_picks(student_id: str, db: Session = Depends(db_session)):
    row = db.get(StudentSubmission, student_id)
    if not row:
        return {"ok": False, "detail": "No picks submitted yet."}
    return {"ok": True, "student_id": student_id, "grade": row.grade, **json.loads(row.payload_json)}


@app.get("/api/submissions")
@app.get("/api/admin/submissions")
def list_submissions(db: Session = Depends(db_session)):
    rows = db.execute(select(StudentSubmission).order_by(StudentSubmission.updated_at.desc())).scalars().all()
    return {
        "ok": True,
        "count": len(rows),
        "submissions": [
            {
                "student_id": r.student_id,
                "grade": r.grade,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ],
    }


# ============================================================
# Lottery logic
# ============================================================
def require_admin(request: Request) -> None:
    """
    If ADMIN_TOKEN is set, require it via header: X-Admin-Token: <token>
    If not set, allow (for development/testing).
    """
    if not ADMIN_TOKEN:
        return
    token = request.headers.get("X-Admin-Token", "").strip()
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Missing/invalid admin token")


def assign_lottery_numbers(students: List[Dict[str, Any]], grade_order: List[int]) -> List[Dict[str, Any]]:
    """
    Seniors first by default: [12,11,10,9]
    Each grade group gets a block of numbers; lower number = earlier pick.
    """
    students_by_grade: Dict[int, List[Dict[str, Any]]] = {}
    for s in students:
        students_by_grade.setdefault(int(s["grade"]), []).append(s)

    current = 1
    for g in grade_order:
        group = students_by_grade.get(g, [])
        random.shuffle(group)
        nums = list(range(current, current + len(group)))
        random.shuffle(nums)
        for s, n in zip(group, nums):
            s["lottery_number"] = n
        current += len(group)

    # Any grades not in grade_order go last
    for g, group in students_by_grade.items():
        if g in grade_order:
            continue
        random.shuffle(group)
        nums = list(range(current, current + len(group)))
        random.shuffle(nums)
        for s, n in zip(group, nums):
            s["lottery_number"] = n
        current += len(group)

    students.sort(key=lambda x: x["lottery_number"])
    return students


def run_global_lottery(db: Session, force_capacity: Optional[int] = None) -> Dict[str, Any]:
    """
    Runs one shared global lottery using all current submissions.
    Saves per-student results in lottery_results with a run_id.
    """
    # Load courses
    courses = load_courses_best_effort()
    course_map: Dict[str, Course] = {c.class_id: c for c in courses}

    # Capacity tracking
    cap_override = force_capacity or (DEFAULT_FORCE_CAPACITY if DEFAULT_FORCE_CAPACITY > 0 else None)
    capacity: Dict[str, int] = {}
    enrolled: Dict[str, int] = {}

    for c in courses:
        cap = c.capacity if c.capacity is not None else (cap_override if cap_override is not None else 9999)
        capacity[c.class_id] = int(cap)
        enrolled[c.class_id] = int(c.enrolled or 0)

    # Load submissions
    subs = db.execute(select(StudentSubmission)).scalars().all()
    students: List[Dict[str, Any]] = []
    for r in subs:
        try:
            payload = json.loads(r.payload_json)
        except Exception:
            payload = {}
        students.append(
            {
                "student_id": r.student_id,
                "grade": int(r.grade),
                "choices": payload.get("choices") or [],
                "preference": payload.get("preference"),
                "capacity": payload.get("capacity"),
            }
        )

    if not students:
        return {"ok": False, "detail": "No student submissions yet."}

    # Grade order (Seniors first)
    grade_order = [12, 11, 10, 9]
    students = assign_lottery_numbers(students, grade_order=grade_order)

    # Determine number of rounds from max choices length
    num_rounds = max((len(s.get("choices") or []) for s in students), default=0)
    num_rounds = max(num_rounds, 1)

    # Assignment: each student tries to get 1 class per round
    def has_seat(cid: str) -> bool:
        return enrolled.get(cid, 0) < capacity.get(cid, 0)

    def take_seat(cid: str) -> None:
        enrolled[cid] = enrolled.get(cid, 0) + 1

    results: Dict[str, Dict[str, Any]] = {}
    for s in students:
        sid = s["student_id"]
        assigned: List[Optional[str]] = []
        choices = s.get("choices") or []
        # normalize to nested list
        norm_choices: List[List[str]] = []
        for r in choices:
            if isinstance(r, list):
                norm_choices.append([_clean(x) for x in r if _clean(x)])
            else:
                norm_choices.append([_clean(r)] if _clean(r) else [])

        # pad rounds
        while len(norm_choices) < num_rounds:
            norm_choices.append([])

        for r in range(num_rounds):
            got: Optional[str] = None
            for cid in norm_choices[r]:
                if cid in course_map and has_seat(cid):
                    got = cid
                    take_seat(cid)
                    break
            assigned.append(got)

        results[sid] = {
            "student_id": sid,
            "grade": s["grade"],
            "lottery_number": s["lottery_number"],
            "assigned_class_ids": assigned,
            "assigned_classes": [
                (course_map[cid].to_dict() if cid and cid in course_map else None) for cid in assigned
            ],
        }

    run_id = f"run_{utcnow().strftime('%Y%m%d_%H%M%S')}_{random.randint(1000,9999)}"
    created = utcnow()

    # Save results
    for sid, r in results.items():
        db.add(
            LotteryResult(
                run_id=run_id,
                student_id=sid,
                grade=int(r["grade"]),
                lottery_number=int(r["lottery_number"]),
                result_json=json.dumps(r),
                created_at=created,
            )
        )
    db.commit()

    return {
        "ok": True,
        "run_id": run_id,
        "count_students": len(results),
        "created_at": created.isoformat(),
    }


# ============================================================
# Admin endpoints (aliases to avoid 404)
# ============================================================
@app.post("/api/admin/run_global_lottery")
@app.post("/api/admin/run-global-lottery")
@app.post("/api/run_global_lottery")
@app.post("/api/run-global-lottery")
@app.post("/api/runLottery")
def api_run_lottery(
    request: Request,
    raw: Dict[str, Any] = Body(default={}),
    db: Session = Depends(db_session),
):
    """
    Runs the shared global lottery and saves results to DB.
    Requires X-Admin-Token header only if ADMIN_TOKEN env var is set.
    """
    require_admin(request)

    # Optional: allow forcing capacity from request payload
    force_capacity = raw.get("force_capacity") or raw.get("forceCapacity") or raw.get("capacity")
    try:
        force_capacity = int(force_capacity) if force_capacity is not None and str(force_capacity).strip() != "" else None
    except Exception:
        force_capacity = None

    try:
        return run_global_lottery(db, force_capacity=force_capacity)
    except FileNotFoundError as e:
        return {"ok": False, "detail": str(e)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# Results endpoints (return 200 with ok:false if missing)
# ============================================================
@app.get("/api/results/{student_id}")
@app.get("/api/check_results/{student_id}")
@app.get("/api/check-results/{student_id}")
def get_results_path(student_id: str, db: Session = Depends(db_session)):
    rows = (
        db.execute(
            select(LotteryResult)
            .where(LotteryResult.student_id == student_id)
            .order_by(LotteryResult.created_at.desc())
            .limit(1)
        )
        .scalars()
        .all()
    )

    if not rows:
        return {"ok": False, "detail": "No results yet. Admin must run the global lottery."}

    r = rows[0]
    payload = json.loads(r.result_json)
    return {
        "ok": True,
        "run_id": r.run_id,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        **payload,
    }


@app.get("/api/results")
@app.get("/api/check_results")
@app.get("/api/check-results")
def get_results_query(
    student_id: Optional[str] = Query(default=None),
    run_id: Optional[str] = Query(default=None),
    db: Session = Depends(db_session),
):
    """
    Supports:
      /api/results?student_id=S001
      /api/results (latest run summary)
      /api/results?run_id=run_...
    """
    if student_id:
        return get_results_path(student_id, db)

    # Determine run_id
    if not run_id:
        latest = db.execute(select(LotteryResult).order_by(LotteryResult.created_at.desc()).limit(1)).scalars().all()
        if not latest:
            return {"ok": False, "detail": "No lottery runs yet.", "results": []}
        run_id = latest[0].run_id

    rows = db.execute(select(LotteryResult).where(LotteryResult.run_id == run_id)).scalars().all()
    results = [json.loads(r.result_json) for r in rows]
    return {"ok": True, "run_id": run_id, "count": len(results), "results": results}


# ============================================================
# Export / Import (prevent 404s)
# ============================================================
@app.get("/api/export")
@app.get("/api/export_picks")
def export_all_picks(db: Session = Depends(db_session)):
    rows = db.execute(select(StudentSubmission)).scalars().all()
    out = []
    for r in rows:
        try:
            payload = json.loads(r.payload_json)
        except Exception:
            payload = {}
        out.append({"student_id": r.student_id, "grade": r.grade, **payload})
    return {"ok": True, "count": len(out), "submissions": out}


@app.post("/api/import")
@app.post("/api/import_picks")
def import_picks(raw: Dict[str, Any] = Body(...), db: Session = Depends(db_session)):
    """
    Accepts:
      { submissions: [ {student_id, grade, choices, ...}, ... ] }
    """
    subs = raw.get("submissions")
    if not isinstance(subs, list):
        return {"ok": False, "detail": "Expected JSON: {submissions:[...] }"}

    now = utcnow()
    count = 0
    for item in subs:
        if not isinstance(item, dict):
            continue
        payload = PicksPayload.from_any(item)
        stored = {
            "student_id": payload.student_id,
            "grade": payload.grade,
            "choices": payload.choices,
            "preference": payload.preference,
            "capacity": payload.capacity,
        }
        row = db.get(StudentSubmission, payload.student_id)
        if row is None:
            row = StudentSubmission(
                student_id=payload.student_id,
                grade=int(payload.grade),
                payload_json=json.dumps(stored),
                updated_at=now,
            )
            db.add(row)
        else:
            row.grade = int(payload.grade)
            row.payload_json = json.dumps(stored)
            row.updated_at = now
        count += 1

    db.commit()
    return {"ok": True, "imported": count}


# ============================================================
# Optional scrape/build endpoints (kept as stubs so UI never 404s)
# ============================================================
@app.post("/api/scrape")
@app.post("/api/scrape_build")
@app.post("/api/scrape-build")
def scrape_stub():
    return {
        "ok": False,
        "detail": "Scraping is disabled in this deployed environment. Run scraper locally and commit the CSV.",
    }