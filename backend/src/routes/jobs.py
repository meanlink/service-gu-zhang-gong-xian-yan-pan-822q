from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from src.config.database import get_db
from src.models import Job
from src.schemas.job import JobInput
from src.middlewares.auth import current_user, can_write, admin_only
from src.services import jobs, blind
from src.services.audit import record
from src.utils.serialization import job_dict
router=APIRouter(prefix='/jobs')
@router.get('')
def listing(db=Depends(get_db),u=Depends(current_user)):
    acts=blind.active_activities(db);out=[]
    for j in db.scalars(select(Job).order_by(Job.id.desc()).limit(100)):
        d=job_dict(j);reason=blind.job_constraint(db,j,acts)
        if reason:d['result']={};d['error']='';d['quarantined']=reason
        out.append(d)
    return out
@router.post('',status_code=201)
def create(data:JobInput,db=Depends(get_db),u=Depends(can_write)):
    j=jobs.create(db,data,u)
    activity=blind.dataset_constraint(db,data.dataset_id)
    if activity:
        # 调参仅用开放部分：隔离期内的批次，新分析自动限定开放样本
        j.blind_activity_id=activity.id;j.blind_scope='open'
    record(db,u.email,'job.create',{'id':j.id,'params':j.params,'blind_scope':j.blind_scope or 'full'})
    db.commit(); jobs.enqueue(j.id); return job_dict(j)
@router.get('/{id}')
def detail(id:int,db=Depends(get_db),u=Depends(current_user)):
    j=db.get(Job,id)
    if not j: raise HTTPException(404,'分析任务不存在')
    reason=blind.job_constraint(db,j)
    if reason: raise HTTPException(403,reason)
    return job_dict(j)
@router.post('/{id}/approve')
def approve(id:int,db=Depends(get_db),u=Depends(admin_only)):
    j=db.get(Job,id)
    if not j: raise HTTPException(404,'分析任务不存在')
    reason=blind.job_constraint(db,j)
    if reason: raise HTTPException(403,reason)
    if j.status!='completed':raise HTTPException(409,'仅已完成结果可以批准')
    j.approved=True; record(db,u.email,'job.approve',{'id':id}); db.commit()
    return job_dict(j)
