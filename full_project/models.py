# models.py
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.sql import func
from database import Base

class Student(Base):
    __tablename__ = "students"
    student_id = Column(String, primary_key=True, index=True)
    grade = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Pick(Base):
    __tablename__ = "picks"
    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(String, ForeignKey("students.student_id"), index=True, nullable=False)
    round = Column(Integer, nullable=False)  # 1..4
    rank = Column(Integer, nullable=False)   # 1..N
    class_id = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("student_id", "round", "rank", name="uq_student_round_rank"),
    )

class LotteryRun(Base):
    __tablename__ = "lottery_runs"
    id = Column(Integer, primary_key=True, index=True)
    status = Column(String, nullable=False, default="completed")  # simple
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Assignment(Base):
    __tablename__ = "assignments"
    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("lottery_runs.id"), index=True, nullable=False)
    student_id = Column(String, ForeignKey("students.student_id"), index=True, nullable=False)
    round = Column(Integer, nullable=False)  # 1..4
    class_id = Column(String, nullable=True) # None if unassigned

    __table_args__ = (
        UniqueConstraint("run_id", "student_id", "round", name="uq_run_student_round"),
    )