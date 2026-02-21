"""SQLAlchemy ORM models.

These models are shared by server.py and (optionally) scripts/tests.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint # type: ignore

from full_project.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ----------------------------
# Legacy / optional tables
# ----------------------------
class Student(Base):
    __tablename__ = "students"
    id = Column(String, primary_key=True, index=True)  # student ID
    grade = Column(Integer, nullable=False)


class Pick(Base):
    __tablename__ = "picks"
    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(String, ForeignKey("students.id"))
    rank = Column(Integer, nullable=False)
    crn = Column(String, nullable=False)


class LotteryRun(Base):
    __tablename__ = "lottery_runs"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), default=utcnow)


class Assignment(Base):
    __tablename__ = "assignments"
    id = Column(Integer, primary_key=True, index=True)
    lottery_run_id = Column(Integer, ForeignKey("lottery_runs.id"))
    student_id = Column(String, ForeignKey("students.id"))
    crn = Column(String, nullable=False)
    rank = Column(Integer, nullable=False)


# ----------------------------
# Tables used by the current frontend (index.html) + API (server.py)
# ----------------------------
class StudentSubmission(Base):
    """Latest submission per student (stored as JSON string for portability)."""

    __tablename__ = "student_submissions"
    student_id = Column(String, primary_key=True, index=True)
    grade = Column(Integer, nullable=False)
    payload_json = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class LotteryResult(Base):
    """One row per student per lottery run (stored as JSON string for portability)."""

    __tablename__ = "lottery_results"
    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    run_id = Column(String, nullable=False, index=True)
    student_id = Column(String, nullable=False, index=True)
    grade = Column(Integer, nullable=False)
    lottery_number = Column(Integer, nullable=False)
    result_json = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint("run_id", "student_id", name="uq_lottery_results_run_student"),
    )
