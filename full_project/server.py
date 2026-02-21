# server.py
from __future__ import annotations

import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    String,
    Text,
    create_engine,
    select,
    delete,
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session

# ============================================================
# Paths / Config
# ============================================================
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
IMPORTANT_DIR = BASE_DIR / "important_files"

# Your tidy CSV (created by tidy_courses_scv.py)
TIDY_CSV = IMPORTANT_DIR / "davidson_courses_tidy.csv"

# Admin token to protect global lottery endpoint
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")  # set this in DigitalOcean env vars
DEFAULT_FORCE_CAPACITY = int(os.getenv("FORCE_CAPACITY_DEFAULT", "25"))

# Database URL (DigitalOcean Postgres) or fallback to SQLite file locally
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if not DATABASE_URL:
    # fallback for local/dev
    DATABASE_URL = f"sqlite:///{(BASE_DIR / 'app.db').as_posix()}"

# SQLAlchemy setup
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ============================================================
# DB Models
# ============================================================
class StudentSubmission(Base):
    __tablename__ = "student_submissions"

    student_id = Column(String(64), primary_key=True)
    grade = Column(Integer, nullable=False)
    # JSON string: {"choices":[[...],[...],[...],[...]], "preference":"...", "capacity":25}
    payload_json = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class LotteryResult(Base):
    __tablename__ = "lottery_results"

    # one result row per student per run
    run_id = Column(String(64), primary_key=True)
    student_id = Column(String(64), primary_key=True)

    grade = Column(Integer, nullable=False)
    lottery_number = Column(Integer, nullable=False)

    # JSON string: {"assigned":["CRN1","CRN2",null,"CRN4"]}
    result_json = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


# Create tables
Base.metadata.create_all(bind=engine)


def db_session() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================================
# CSV -> Class parsing
# ============================================================
def _clean(x: Any) -> str:
    return "" if x is None else str(x).strip()


def _parse_crs_sec(crs_sec: str) -> Tuple[str, str, str]:
    """
    From tidy CSV: 'AFR-101-A' (in column 'Crs & Sec')
    """
    s = _clean(crs_sec)
    m = re.match(r"^([A-Za-z]{2,})-(\d+)-([A-Za-z0-9]+)$", s)
    if not m:
        return ("", "", "")
    return (m.group(1).upper(), m.group(2), m.group(3))


def _parse_seats(seats_left: str) -> Tuple[Optional[int], Optional[int]]:
    """
    tidy_courses_scv.py writes Seats Left as either:
      - "enrolled/capacity"  (ex: "12/25")
      - "12"                (enrolled only)
      - ""                  (unknown)
    Returns (enrolled, capacity)
    """
    s = _clean(seats_left)
    if not s:
        return (None, None)
    if "/" in s:
        a, b = s.split("/", 1)
        try:
            return (int(a.strip()), int(b.strip()))
        except ValueError:
            return (None, None)
    try:
        return (int(s), None)
    except ValueError:
        return (None, None)


def load_classes_from_tidy_csv() -> List[Dict[str, Any]]:
    """
    Returns a list of class dicts the frontend can consume.
    """
    import csv

    if not TIDY_CSV.exists():
        raise FileNotFoundError(f"Tidy CSV not found: {TIDY_CSV}")

    out: List[Dict[str, Any]] = []
    with TIDY_CSV.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            crn = _clean(row.get("CRN"))
            title = _clean(row.get("Title"))
            cred = _clean(row.get("Cred"))
            days = _clean(row.get("Days"))
            time_str = _clean(row.get("Time"))
            room = _clean(row.get("Room"))
            instructor = _clean(row.get("Instructor"))
            notes = _clean(row.get("Notes"))
            grad_reqs = _clean(row.get("Grad. Reqs."))
            seats_left = _clean(row.get("Seats Left"))
            crs_sec = _clean(row.get("Crs & Sec"))

            subject, course_number, section = _parse_crs_sec(crs_sec)
            enrolled, capacity = _parse_seats(seats_left)

            out.append(
                {
                    "class_id": crn,  # primary key for frontend
                    "crn": crn,
                    "crs_sec": crs_sec,
                    "subject": subject,
                    "course_number": course_number,
                    "section": section,
                    "title": title,
                    "credits": cred,
                    "days": days,
                    "time": time_str,
                    "room": room,
                    "instructor": instructor,
                    "notes": notes,
                    "grad_reqs": grad_reqs,
                    "enrolled": enrolled,
                    "capacity": capacity,
                }
            )
    return out


# ============================================================
# Lottery engine (global run)
# ============================================================
def assign_lottery_numbers(students: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    Assign unique lottery numbers. Seniors (12) first (lowest numbers), then 11,10,9.
    Returns mapping student_id -> lottery_number
    """
    import random

    grades_order = [12, 11, 10, 9]
    by_grade: Dict[int, List[Dict[str, Any]]] = {g: [] for g in grades_order}
    for s in students:
        by_grade.get(int(s["grade"]), []).append(s)

    current = 1
    mapping: Dict[str, int] = {}
    for g in grades_order:
        group = by_grade.get(g, [])
        random.shuffle(group)
        nums = list(range(current, current + len(group)))
        random.shuffle(nums)
        for s, n in zip(group, nums):
            mapping[s["student_id"]] = n
        current += len(group)
    return mapping


def run_global_lottery(
    classes: List[Dict[str, Any]],
    submissions: List[Dict[str, Any]],
    force_capacity: int,
) -> Dict[str, Dict[str, Any]]:
    """
    Runs 4 rounds, each round student picks are a ranked list of class_ids.
    Places students in lottery order; first available choice wins.
    Returns:
      student_id -> {"assigned":[...], "lottery_number": n, "grade": g}
    """
    # capacities
    cap: Dict[str, int] = {}
    roster: Dict[str, List[str]] = {}

    for c in classes:
        cid = c["class_id"]
        roster[cid] = []
        # Use forced capacity if provided, otherwise use csv capacity or fallback
        cap[cid] = int(c.get("capacity") or force_capacity)

    # lottery order
    lotto_map = assign_lottery_numbers(submissions)

    # sort students by lottery number ascending
    ordered = sorted(submissions, key=lambda s: lotto_map.get(s["student_id"], 10**9))

    # rounds
    results: Dict[str, Dict[str, Any]] = {}
    for s in ordered:
        sid = s["student_id"]
        grade = int(s["grade"])
        choices = s["choices"]  # List[List[str]]
        assigned: List[Optional[str]] = [None] * len(choices)

        for round_idx in range(len(choices)):
            for cid in choices[round_idx]:
                if cid not in roster:
                    continue
                if len(roster[cid]) < cap[cid]:
                    roster[cid].append(sid)
                    assigned[round_idx] = cid
                    break

        results[sid] = {
            "student_id": sid,
            "grade": grade,
            "lottery_number": int(lotto_map.get(sid, 0) or 0),
            "assigned": assigned,
        }

    return results


# ============================================================
# API Schemas
# ============================================================
class PicksPayload(BaseModel):
    student_id: str = Field(..., min_length=1, max_length=64)
    grade: int = Field(..., ge=1, le=12)
    # 4 rounds, each is a ranked list of class_ids (CRNs)
    choices: List[List[str]] = Field(default_factory=list)
    preference: Optional[str] = None
    capacity: Optional[int] = Field(default=None, ge=1, le=500)


class AdminRunRequest(BaseModel):
    # Optional capacity override for testing
    force_capacity: Optional[int] = Field(default=None, ge=1, le=500)


# ============================================================
# FastAPI App
# ============================================================
app = FastAPI()

# CORS (helps when you test from other origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- Static serving ----
# IMPORTANT: do NOT mount StaticFiles at "/" or it can shadow /api routes.
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return JSONResponse(
        {"ok": True, "message": "Server running, but static/index.html not found."},
        status_code=200,
    )


@app.get("/favicon.ico")
def favicon():
    ico = STATIC_DIR / "favicon.ico"
    if ico.exists():
        return FileResponse(str(ico))
    # harmless: stop console spam
    return JSONResponse({}, status_code=204)


# ---- Health / status ----
@app.get("/api/health")
def health():
    return {"ok": True, "time": datetime.now(timezone.utc).isoformat()}


@app.get("/api/status")
def status(db: Session = Depends(db_session)):
    tidy_exists = TIDY_CSV.exists()
    # count submissions
    sub_count = db.scalar(select(StudentSubmission).count()) if hasattr(select(StudentSubmission), "count") else None
    # SQLAlchemy 2.0 doesn't support .count() on select(model); do a safe count:
    if sub_count is None:
        sub_count = db.execute(select(StudentSubmission.student_id)).all()
        sub_count = len(sub_count)
    return {
        "ok": True,
        "tidy_csv_exists": tidy_exists,
        "tidy_csv_path": str(TIDY_CSV),
        "submissions_count": sub_count,
    }


# ---- Courses ----
@app.get("/api/classes")
def api_classes(wrap: bool = False):
    classes = load_classes_from_tidy_csv()
    return {"classes": classes, "count": len(classes)} if wrap else classes


# ---- Picks submission ----
@app.post("/api/picks")
def submit_picks(payload: PicksPayload, db: Session = Depends(db_session)):
    """
    Saves / overwrites a student's picks.
    """
    now = datetime.now(timezone.utc)

    # Normalize choices to strings, remove blanks
    clean_choices: List[List[str]] = []
    for round_list in payload.choices:
        r = []
        for cid in round_list:
            cid = _clean(cid)
            if cid:
                r.append(cid)
        clean_choices.append(r)

    stored = {
        "choices": clean_choices,
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
    return {"ok": True, "student_id": payload.student_id}


@app.get("/api/picks/{student_id}")
def get_picks(student_id: str, db: Session = Depends(db_session)):
    row = db.get(StudentSubmission, student_id)
    if row is None:
        raise HTTPException(status_code=404, detail="No picks submitted for this student_id")
    data = json.loads(row.payload_json)
    return {"student_id": row.student_id, "grade": row.grade, **data, "updated_at": row.updated_at.isoformat()}


# ---- Results ----
@app.get("/api/results/{student_id}")
def get_results(student_id: str, db: Session = Depends(db_session)):
    """
    Returns the latest result for a student, if a global run has been executed.
    """
    # latest run for student
    rows = db.execute(
        select(LotteryResult)
        .where(LotteryResult.student_id == student_id)
        .order_by(LotteryResult.created_at.desc())
        .limit(1)
    ).scalars().all()

    if not rows:
        raise HTTPException(status_code=404, detail="No results yet. Admin must run the global lottery.")

    r = rows[0]
    return {
        "student_id": r.student_id,
        "grade": r.grade,
        "lottery_number": r.lottery_number,
        "run_id": r.run_id,
        **json.loads(r.result_json),
        "created_at": r.created_at.isoformat(),
    }


@app.get("/api/results")
def get_results_all(
    run_id: Optional[str] = Query(default=None),
    db: Session = Depends(db_session),
):
    """
    Returns all results for a specific run_id (or latest run overall if not provided).
    Useful for admin/debug.
    """
    if run_id is None:
        latest = db.execute(select(LotteryResult.run_id).order_by(LotteryResult.created_at.desc()).limit(1)).all()
        if not latest:
            return {"run_id": None, "results": []}
        run_id = latest[0][0]

    rows = db.execute(select(LotteryResult).where(LotteryResult.run_id == run_id)).scalars().all()
    results = []
    for r in rows:
        obj = {
            "student_id": r.student_id,
            "grade": r.grade,
            "lottery_number": r.lottery_number,
            **json.loads(r.result_json),
        }
        results.append(obj)

    return {"run_id": run_id, "count": len(results), "results": results}


# ---- Admin: Run Global Lottery ----
def _require_admin(x_admin_token: Optional[str]) -> None:
    if not ADMIN_TOKEN:
        # If you forgot to set ADMIN_TOKEN, block by default (safer)
        raise HTTPException(status_code=500, detail="ADMIN_TOKEN not set on server")
    if not x_admin_token or x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized (missing/invalid admin token)")


@app.post("/api/admin/run-lottery")
def admin_run_lottery(
    req: AdminRunRequest,
    x_admin_token: Optional[str] = Header(default=None),
    db: Session = Depends(db_session),
):
    _require_admin(x_admin_token)

    # Load classes
    try:
        classes = load_classes_from_tidy_csv()
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Load submissions
    sub_rows = db.execute(select(StudentSubmission)).scalars().all()
    submissions: List[Dict[str, Any]] = []
    for row in sub_rows:
        payload = json.loads(row.payload_json)
        submissions.append(
            {
                "student_id": row.student_id,
                "grade": row.grade,
                "choices": payload.get("choices", []),
                "capacity": payload.get("capacity"),
                "preference": payload.get("preference"),
            }
        )

    if not submissions:
        raise HTTPException(status_code=400, detail="No student picks submitted yet")

    # capacity override: request -> else DEFAULT_FORCE_CAPACITY
    force_capacity = int(req.force_capacity or DEFAULT_FORCE_CAPACITY)

    # run
    results_map = run_global_lottery(classes, submissions, force_capacity=force_capacity)

    # write results as a new run_id
    run_id = secrets.token_hex(8)
    now = datetime.now(timezone.utc)

    # remove old results for same student in this run_id (not needed, but safe)
    # store
    for sid, r in results_map.items():
        db.add(
            LotteryResult(
                run_id=run_id,
                student_id=sid,
                grade=int(r["grade"]),
                lottery_number=int(r["lottery_number"]),
                result_json=json.dumps({"assigned": r["assigned"]}),
                created_at=now,
            )
        )

    db.commit()
    return {"ok": True, "run_id": run_id, "students": len(results_map)}


@app.post("/api/admin/clear-results")
def admin_clear_results(
    x_admin_token: Optional[str] = Header(default=None),
    db: Session = Depends(db_session),
):
    _require_admin(x_admin_token)
    db.execute(delete(LotteryResult))
    db.commit()
    return {"ok": True}


# ============================================================
# Helpful 404 debugging for API routes
# ============================================================
@app.exception_handler(404)
def not_found(_, __):
    # Keep FastAPI default JSON shape so frontend can display it
    return JSONResponse({"detail": "Not Found"}, status_code=404)