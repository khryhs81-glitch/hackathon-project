# server.py
import os
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import engine, Base, get_db
from models import Student, Pick, LotteryRun, Assignment

import schedulenew  # your scheduler file

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")

app = FastAPI()

# Serve your frontend (static/index.html)
app.mount("/", StaticFiles(directory="static", html=True), name="static")

@app.on_event("startup")
def startup():
    # Simple “migration”: create tables if missing
    Base.metadata.create_all(bind=engine)

# ---------------------------
# Pydantic request models
# ---------------------------
class StudentPicks(BaseModel):
    student_id: str = Field(..., min_length=1)
    grade: int = Field(..., ge=9, le=12)
    choices: List[List[str]] = Field(..., min_length=4, max_length=4)

class SubmitPicksRequest(BaseModel):
    student: StudentPicks

class GlobalRunRequest(BaseModel):
    force_capacity: Optional[int] = Field(default=None, ge=1)

# ---------------------------
# Helpers
# ---------------------------
def require_admin(x_admin_token: str = Header(default="")):
    if not ADMIN_TOKEN:
        raise HTTPException(status_code=500, detail="ADMIN_TOKEN is not set on server.")
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid admin token.")

def normalize_choices(choices: List[List[str]], max_per_round: int = 5) -> List[List[str]]:
    out: List[List[str]] = []
    for r in range(4):
        round_list = choices[r] if r < len(choices) and isinstance(choices[r], list) else []
        round_list = [str(x).strip() for x in round_list if str(x).strip()]
        out.append(round_list[:max_per_round])
    return out

def latest_run_id(db: Session) -> Optional[int]:
    row = db.query(LotteryRun).order_by(LotteryRun.id.desc()).first()
    return row.id if row else None

# ---------------------------
# Student: submit picks
# ---------------------------
@app.post("/api/submit_picks")
def submit_picks(req: SubmitPicksRequest, db: Session = Depends(get_db)):
    s = req.student
    choices = normalize_choices(s.choices)

    # Upsert student
    student = db.query(Student).filter(Student.student_id == s.student_id).first()
    if not student:
        student = Student(student_id=s.student_id, grade=s.grade)
        db.add(student)
    else:
        student.grade = s.grade

    # Delete previous picks and replace (simplest approach)
    db.query(Pick).filter(Pick.student_id == s.student_id).delete()

    # Insert picks
    for round_index, picks in enumerate(choices, start=1):
        for rank_index, class_id in enumerate(picks, start=1):
            db.add(Pick(
                student_id=s.student_id,
                round=round_index,
                rank=rank_index,
                class_id=class_id
            ))

    db.commit()
    return {"ok": True, "message": "Picks saved."}

# ---------------------------
# Student: view my picks
# ---------------------------
@app.get("/api/picks/{student_id}")
def get_picks(student_id: str, db: Session = Depends(get_db)):
    rows = db.query(Pick).filter(Pick.student_id == student_id).order_by(Pick.round, Pick.rank).all()
    choices = [[] for _ in range(4)]
    for p in rows:
        if 1 <= p.round <= 4:
            choices[p.round - 1].append(p.class_id)
    return {"ok": True, "student_id": student_id, "choices": choices}

# ---------------------------
# Admin: run ONE global lottery for everyone
# ---------------------------
@app.post("/api/admin/run_global_lottery")
def run_global_lottery(
    body: GlobalRunRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    # Collect all students
    students = db.query(Student).all()
    if not students:
        return JSONResponse(status_code=400, content={"ok": False, "error": "No students have submitted picks yet."})

    # Build student payloads from DB picks
    student_payloads: List[Dict[str, Any]] = []
    for st in students:
        picks = db.query(Pick).filter(Pick.student_id == st.student_id).order_by(Pick.round, Pick.rank).all()
        choices = [[] for _ in range(4)]
        for p in picks:
            if 1 <= p.round <= 4:
                choices[p.round - 1].append(p.class_id)

        student_payloads.append({
            "student_id": st.student_id,
            "grade": st.grade,
            "choices": choices
        })

    # Call your scheduler
    # IMPORTANT: adjust this line to match your schedulenew API.
    if hasattr(schedulenew, "run_lottery"):
        results = schedulenew.run_lottery(student_payloads, force_capacity=body.force_capacity)
    else:
        raise HTTPException(status_code=500, detail="schedulenew.py must expose run_lottery(students, force_capacity=...).")

    # Create a new run
    run = LotteryRun(status="completed")
    db.add(run)
    db.commit()
    db.refresh(run)

    # Store assignments
    # Expected shape assumption:
    # results = { "students": [ { "student_id": "...", "assigned_classes": [cid1, cid2, cid3, cid4] } ] }
    # If your scheduler output differs, we’ll adapt this mapping.
    students_out = results.get("students", results)  # fallback if it returns list directly

    # wipe any accidental partials for this run id (should be none)
    db.query(Assignment).filter(Assignment.run_id == run.id).delete()

    for sres in students_out:
        sid = sres.get("student_id")
        assigned = sres.get("assigned_classes", [])
        # ensure length 4
        assigned = (assigned + [None, None, None, None])[:4]
        for r in range(1, 5):
            db.add(Assignment(run_id=run.id, student_id=sid, round=r, class_id=assigned[r-1]))

    db.commit()
    return {"ok": True, "run_id": run.id}

# ---------------------------
# Student: get results from latest run
# ---------------------------
@app.get("/api/results/{student_id}")
def get_results(student_id: str, db: Session = Depends(get_db)):
    run_id = latest_run_id(db)
    if not run_id:
        return {"ok": True, "run_id": None, "student_id": student_id, "assigned_classes": [None, None, None, None]}

    rows = db.query(Assignment).filter(
        Assignment.run_id == run_id,
        Assignment.student_id == student_id
    ).order_by(Assignment.round).all()

    assigned = [None, None, None, None]
    for a in rows:
        if 1 <= a.round <= 4:
            assigned[a.round - 1] = a.class_id

    return {"ok": True, "run_id": run_id, "student_id": student_id, "assigned_classes": assigned}