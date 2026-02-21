from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import scrape_davidson_courses as scraper
import tidy_courses_scv as tidy
import schedulenew as scheduler

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
IMPORTANT_DIR = BASE_DIR / "important_files"

SCRAPE_PREFIX = BASE_DIR / "davidson_courses"
NORMALIZED_CSV = Path(f"{SCRAPE_PREFIX}_normalized.csv")
TIDY_CSV = IMPORTANT_DIR / "davidson_courses_tidy.csv"

app = FastAPI(title="Davidson Schedule Maker")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR.mkdir(exist_ok=True)
IMPORTANT_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ClassOut(BaseModel):
    class_id: str
    subject: str = ""
    course_number: str = ""
    section: str = ""
    title: str = ""
    credits: Optional[float] = None
    instructor: str = ""
    meeting_days: str = ""
    time_range: str = ""
    start_time: str = ""
    end_time: str = ""
    building: str = ""
    room: str = ""
    enrolled: Optional[int] = None
    capacity: Optional[int] = None


class StudentIn(BaseModel):
    student_id: str
    grade: int = 12
    choices: List[List[str]] = Field(default_factory=list)


class LotteryRequest(BaseModel):
    students: List[StudentIn] = Field(default_factory=list)
    force_capacity: Optional[int] = 25


@app.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        return HTMLResponse("<h2>Missing static/index.html</h2>", status_code=500)
    return HTMLResponse(index_path.read_text(encoding="utf-8"))


@app.get("/api/classes", response_model=List[ClassOut])
def get_classes() -> List[ClassOut]:
    try:
        classes = scheduler.load_classes_from_tidy_csv(scheduler.TIDY_CSV_PATH)
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=500,
            detail=f"{e}. If you haven't generated the tidy CSV yet, call POST /api/refresh first.",
        )

    return [
        ClassOut(
            class_id=c.class_id,
            subject=c.subject,
            course_number=c.course_number,
            section=c.section,
            title=c.title,
            credits=c.credits,
            instructor=c.instructor,
            meeting_days=c.meeting_days,
            time_range=c.time_range,
            start_time=c.start_time,
            end_time=c.end_time,
            building=c.building,
            room=c.room,
            enrolled=c.enrolled,
            capacity=c.capacity,
        )
        for c in classes
    ]


@app.post("/api/run_lottery")
def run_lottery(req: LotteryRequest) -> Dict[str, Any]:
    payload = [s.model_dump() for s in req.students]
    try:
        return scheduler.run_lottery_from_payload(
            payload,
            force_capacity=req.force_capacity,
            grade_order=[12, 11, 10, 9],
        )
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=500,
            detail=f"{e}. Generate a tidy CSV first (POST /api/refresh) or place it at: {scheduler.TIDY_CSV_PATH}",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/refresh")
async def refresh(
    term: str = "202502",
    limit: int = 50,
    headless: bool = True,
    test_seats_available: int = 25,
) -> Dict[str, Any]:
    """
    1) Run the Playwright scraper -> writes *normalized.csv
    2) Run tidy conversion -> writes important_files/davidson_courses_tidy.csv
    """
    try:
        await scraper.run(
            term_code=term,
            limit=limit,
            out_prefix=str(SCRAPE_PREFIX),
            headless=headless,
            discover_wait=10000,
            test_seats_available=test_seats_available,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scrape failed: {e}")

    try:
        out_path = tidy.make_tidy_csv(src=NORMALIZED_CSV, out=TIDY_CSV)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Tidy conversion failed: {e}")

    return {
        "ok": True,
        "normalized_csv": str(NORMALIZED_CSV),
        "tidy_csv": str(out_path),
        "note": "Now open / and click 'Reload Classes'.",
    }