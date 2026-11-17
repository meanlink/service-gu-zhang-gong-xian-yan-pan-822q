from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from src.config.database import get_db
from src.models import BlindActivity, BlindIncident, Dataset
from src.schemas.blind import BlindInput, LockInput
from src.middlewares.auth import current_user, admin_only
from src.services import blind, jobs as job_service
from src.services.audit import record
from src.utils.serialization import blind_dict
router = APIRouter(prefix='/blind-activities')

def get_activity(db, id):
    a = db.get(BlindActivity, id)
    if not a: raise HTTPException(404, '盲验活动不存在')
    return a

def describe(db, a):
    datasets = [{'id': d.id, 'name': d.name} for d in
                (db.get(Dataset, i) for i in (a.dataset_ids or [])) if d]
    names = '、'.join('「' + d['name'] + '」' for d in datasets)
    reasons = {
        'tuning': [f'批次{names}处于盲验隔离：调参仅使用开放样本，封存事件与结果按越权拒绝',
                   '历史全量分析与归档下载在揭盲前同样受限'],
        'locked': [f'候选分析已锁定（任务 #{a.candidate_job_id}），参数固定不再更换',
                   '封存事件与结果仍按越权拒绝，等待负责人受理揭盲'],
        'unblinding': ['揭盲已受理，封存部分正以锁定参数计算；事故已消费，即使失败也不退回可用'],
        'unblind_failed': [f'封存计算失败：{a.error or "未知原因"}。可重试，重试不重复揭盲，事故不退回可用'],
        'unblinded': ['已揭盲公布：封存结果、事件与历史全量分析全部解禁'],
    }
    return blind_dict(a, counts=blind.counts(db, a.id), datasets=datasets,
                      isolation=reasons.get(a.status, []))

@router.get('')
def listing(db=Depends(get_db), u=Depends(current_user)):
    return [describe(db, a) for a in db.scalars(select(BlindActivity).order_by(BlindActivity.id.desc()).limit(100))]

@router.post('', status_code=201)
def create(data: BlindInput, db=Depends(get_db), u=Depends(admin_only)):
    a = blind.create_activity(db, data, u)
    record(db, u.email, 'blind.create', {'id': a.id, 'datasets': a.dataset_ids, 'sealed_percent': a.sealed_percent})
    db.commit()
    return describe(db, a)

@router.get('/{id}')
def detail(id: int, db=Depends(get_db), u=Depends(current_user)):
    return describe(db, get_activity(db, id))

@router.get('/{id}/incidents')
def incidents(id: int, side: str = '', db=Depends(get_db), u=Depends(current_user)):
    a = get_activity(db, id)
    q = select(BlindIncident).where(BlindIncident.activity_id == a.id).order_by(BlindIncident.incident_id)
    if side:
        if side not in ('open', 'sealed'): raise HTTPException(422, 'side 仅支持 open 或 sealed')
        q = q.where(BlindIncident.side == side)
    return [{'incident_id': i.incident_id, 'side': i.side, 'state': i.state}
            for i in db.scalars(q.limit(1000))]

@router.post('/{id}/lock')
def lock(id: int, data: LockInput, db=Depends(get_db), u=Depends(admin_only)):
    a = blind.lock_candidate(db, get_activity(db, id), data.job_id)
    record(db, u.email, 'blind.lock', {'id': a.id, 'candidate': a.candidate_job_id, 'params': a.locked_params})
    db.commit()
    return describe(db, a)

@router.post('/{id}/unblind')
def unblind(id: int, db=Depends(get_db), u=Depends(admin_only)):
    a, job = blind.unblind(db, get_activity(db, id), u)
    record(db, u.email, 'blind.unblind', {'id': a.id, 'sealed_job': job.id, 'candidate': a.candidate_job_id})
    db.commit()
    job_service.enqueue(job.id)
    return describe(db, a)
