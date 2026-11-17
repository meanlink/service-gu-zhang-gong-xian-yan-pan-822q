from sqlalchemy import String, JSON, Double, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base
class BlindActivity(Base):
    __tablename__ = 'blind_activities'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    status: Mapped[str] = mapped_column(String(20), default='tuning')
    sealed_percent: Mapped[int] = mapped_column(Integer, default=40)
    salt: Mapped[str] = mapped_column(String(64))  # 服务端划分盐，不出API，保证同事故跨批同侧且不可预测
    dataset_ids: Mapped[list] = mapped_column(JSON, default=list)
    candidate_job_id: Mapped[int | None] = mapped_column(ForeignKey('jobs.id'), nullable=True)
    locked_params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    sealed_job_id: Mapped[int | None] = mapped_column(ForeignKey('jobs.id'), nullable=True)
    error: Mapped[str] = mapped_column(String(1000), default='')
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[float] = mapped_column(Double)
    locked_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    unblinded_at: Mapped[float | None] = mapped_column(Double, nullable=True)
class BlindIncident(Base):
    __tablename__ = 'blind_incidents'
    id: Mapped[int] = mapped_column(primary_key=True)
    activity_id: Mapped[int] = mapped_column(ForeignKey('blind_activities.id'))
    incident_id: Mapped[str] = mapped_column(String(120), unique=True)  # 全局唯一：已受理/已揭盲事故拒绝另开活动复用
    side: Mapped[str] = mapped_column(String(10))
    state: Mapped[str] = mapped_column(String(20), default='assigned')
