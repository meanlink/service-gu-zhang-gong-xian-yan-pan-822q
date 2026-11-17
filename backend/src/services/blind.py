"""盲验活动：按事故编号整组划分开放/封存样本，调参与揭盲全流程隔离。

划分确定性：side = sha256(活动盐:事故编号)，同一事故跨批次归同侧。
事故编号全局唯一注册：已受理或已揭盲的事故拒绝另开活动复用。
"""
import hashlib, secrets, time
from fastapi import HTTPException
from sqlalchemy import select, update, func
from sqlalchemy.exc import IntegrityError
from src.models import BlindActivity, BlindIncident, Dataset, Job

ACTIVE_STATUSES = ('tuning', 'locked', 'unblinding', 'unblind_failed')  # 未揭盲，隔离生效
MIN_SIDE_EVENTS = 30  # 与 analyze 的最少事件数一致，避免划分出无法计算的死角


def side_for(salt, incident_id, sealed_percent):
    digest = hashlib.sha256(f'{salt}:{incident_id}'.encode()).hexdigest()
    return 'sealed' if int(digest[:12], 16) % 100 < sealed_percent else 'open'


def active_activities(db):
    return list(db.scalars(select(BlindActivity).where(BlindActivity.status.in_(ACTIVE_STATUSES))))


def dataset_constraint(db, dataset_id, acts=None):
    """数据集当前是否处于未揭盲活动的隔离中；返回活动或 None。"""
    for a in (acts if acts is not None else active_activities(db)):
        if dataset_id in (a.dataset_ids or []):
            return a
    return None


def side_incidents(db, activity_id, side):
    return set(db.scalars(select(BlindIncident.incident_id).where(
        BlindIncident.activity_id == activity_id, BlindIncident.side == side)))


def open_records(db, dataset, activity):
    """隔离期数据集只暴露开放侧事件；未登记事故的记录一律按封存扣留。"""
    open_ids = side_incidents(db, activity.id, 'open')
    return [r for r in dataset.records if str(r.get('incident_id') or '') in open_ids]


def scoped_records(db, job):
    """worker 计算口径：盲验任务只取本活动对应侧的事故记录。"""
    d = db.get(Dataset, job.dataset_id)
    if not d:
        raise ValueError('数据批次不存在')
    if not job.blind_activity_id or not job.blind_scope:
        return d.records
    ids = side_incidents(db, job.blind_activity_id, job.blind_scope)
    return [r for r in d.records if str(r.get('incident_id') or '') in ids]


def job_constraint(db, job, acts=None):
    """任务结果当前是否应隔离；返回隔离原因或 None。"""
    if job.blind_scope == 'sealed':
        a = db.get(BlindActivity, job.blind_activity_id)
        if a and a.status != 'unblinded':
            return f'封存评估属于盲验活动「{a.name}」，揭盲公布前结果与事件按越权拒绝'
        return None
    if job.blind_scope == 'open':
        return None  # 开放样本结果本就面向调参公开
    a = dataset_constraint(db, job.dataset_id, acts)
    if a:
        return f'该批次已纳入盲验活动「{a.name}」，历史全量分析与下载在揭盲前隔离'
    return None


def create_activity(db, data, user):
    name = data.name.strip()
    if len(name) < 2:
        raise HTTPException(422, '活动名称去除空格后至少需要两个字符')
    if db.scalar(select(BlindActivity).where(BlindActivity.name == name)):
        raise HTTPException(409, '同名盲验活动已存在，请修改名称')
    datasets = []
    for dataset_id in dict.fromkeys(data.dataset_ids):
        d = db.get(Dataset, dataset_id)
        if not d:
            raise HTTPException(404, f'数据批次 {dataset_id} 不存在')
        datasets.append(d)
    per_dataset, all_ids = {}, set()
    for d in datasets:
        ids = set()
        for row in d.records:
            incident = str(row.get('incident_id') or '').strip()
            if not incident:
                raise HTTPException(422, f'批次「{d.name}」存在缺少事故编号的记录，无法纳入盲验划分')
            ids.add(incident)
        per_dataset[d.id] = ids
        all_ids |= ids
    if len(all_ids) < 5:
        raise HTTPException(422, '事故编号少于5个，整组划分没有意义')
    reused = set(db.scalars(select(BlindIncident.incident_id).where(BlindIncident.incident_id.in_(all_ids))))
    if reused:
        sample = '、'.join(sorted(reused)[:8])
        raise HTTPException(409, f'事故 {sample} 等已在其他盲验活动中受理或揭盲，拒绝另开活动复用')
    salt = secrets.token_hex(16)
    split = {inc: side_for(salt, inc, data.sealed_percent) for inc in sorted(all_ids)}
    sides = {d.id: {'open': 0, 'sealed': 0} for d in datasets}
    for d in datasets:
        for row in d.records:
            sides[d.id][split[str(row['incident_id']).strip()]] += 1
    if not any(s['open'] >= MIN_SIDE_EVENTS and s['sealed'] >= MIN_SIDE_EVENTS for s in sides.values()):
        raise HTTPException(422, f'没有任一批次开放与封存两侧均达到{MIN_SIDE_EVENTS}条事件，调参与揭盲无法计算，请调整批次或封存比例')
    activity = BlindActivity(name=name, status='tuning', sealed_percent=data.sealed_percent, salt=salt,
                             dataset_ids=[d.id for d in datasets], created_by=user.id, created_at=time.time())
    db.add(activity)
    try:
        db.flush()
        for incident, side in split.items():
            db.add(BlindIncident(activity_id=activity.id, incident_id=incident, side=side, state='assigned'))
        db.flush()
    except IntegrityError:
        # 并发划分同一批事故：唯一约束兜底，后到的请求按冲突拒绝
        db.rollback()
        raise HTTPException(409, '事故划分与其他盲验活动冲突（同名活动或事故已被受理），请刷新后重试')
    return activity


def lock_candidate(db, activity, job_id):
    """负责人锁定候选分析：仅调参阶段可锁，锁定后不换参。"""
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, '候选分析任务不存在')
    if job.blind_activity_id != activity.id or job.blind_scope != 'open':
        raise HTTPException(422, '候选须是本活动开放样本上完成的分析任务')
    if job.status != 'completed':
        raise HTTPException(409, '候选分析须已计算完成才能锁定')
    sealed_events = sum(1 for r in db.get(Dataset, job.dataset_id).records
                        if str(r.get('incident_id') or '') in side_incidents(db, activity.id, 'sealed'))
    if sealed_events < MIN_SIDE_EVENTS:
        raise HTTPException(422, f'该候选所在批次封存样本不足{MIN_SIDE_EVENTS}条，揭盲无法计算，请更换候选')
    # CAS：仅 tuning 状态可锁定，并发或重复锁定只有一次生效，候选锁定后不换参
    result = db.execute(update(BlindActivity)
                        .where(BlindActivity.id == activity.id, BlindActivity.status == 'tuning')
                        .values(status='locked', candidate_job_id=job.id,
                                locked_params=dict(job.params), locked_at=time.time()))
    if result.rowcount != 1:
        raise HTTPException(409, '候选已锁定，锁定后不再更换参数')
    db.refresh(activity)
    return activity


def unblind(db, activity, user):
    """受理揭盲：并发只受理一次；受理即消费事故，失败不退回；重试复用原封存任务。"""
    if activity.status == 'unblinded':
        raise HTTPException(409, '该活动已完成揭盲并公布，拒绝重复揭盲')
    if activity.status == 'unblinding':
        raise HTTPException(409, '揭盲已受理，封存部分正在计算，请勿重复提交')
    if activity.status == 'unblind_failed':
        # 重试：恢复原候选对应的同一个封存任务重新排队，不新建、不重复消费事故
        job = db.get(Job, activity.sealed_job_id) if activity.sealed_job_id else None
        if not job:
            raise HTTPException(409, '封存评估任务缺失，无法重试，请核查审计记录')
        result = db.execute(update(BlindActivity)
                            .where(BlindActivity.id == activity.id, BlindActivity.status == 'unblind_failed')
                            .values(status='unblinding', error=''))
        if result.rowcount != 1:
            raise HTTPException(409, '揭盲已受理，请勿重复提交')
        job.status = 'queued'
        job.error = ''
        db.flush()
        db.refresh(activity)
        return activity, job
    if activity.status != 'locked':
        raise HTTPException(409, '请先由负责人锁定候选分析，再受理揭盲')
    candidate = db.get(Job, activity.candidate_job_id)
    if not candidate:
        raise HTTPException(409, '候选分析缺失，无法揭盲')
    # CAS：locked -> unblinding 只受理一次，并发请求其余按越序拒绝
    result = db.execute(update(BlindActivity)
                        .where(BlindActivity.id == activity.id, BlindActivity.status == 'locked')
                        .values(status='unblinding', error=''))
    if result.rowcount != 1:
        raise HTTPException(409, '揭盲已受理，封存部分正在计算，请勿重复提交')
    # 受理即消费全部事故：此后即使计算失败，事故也不退回可用池
    db.execute(update(BlindIncident).where(BlindIncident.activity_id == activity.id).values(state='accepted'))
    job = Job(name='封存评估 · ' + activity.name, dataset_id=candidate.dataset_id,
              params=dict(activity.locked_params or candidate.params), status='queued',
              blind_activity_id=activity.id, blind_scope='sealed',
              created_by=user.id, created_at=time.time())
    db.add(job)
    db.flush()
    activity.sealed_job_id = job.id
    db.flush()
    db.refresh(activity)
    return activity, job


def finalize_unblind(db, activity, job):
    """worker 封存计算成功：固定参数的结果随活动公布，事故转为已揭盲。"""
    activity.status = 'unblinded'
    activity.unblinded_at = time.time()
    db.execute(update(BlindIncident).where(BlindIncident.activity_id == activity.id).values(state='unblinded'))


def fail_unblind(db, activity, error):
    """封存计算失败：活动可重试，事故保持已受理不退回。"""
    activity.status = 'unblind_failed'
    activity.error = (error or '')[:990]


def recover(db, record):
    """worker 重启恢复：中断的揭盲恢复原候选继续，不重复揭盲、不丢失锁定。"""
    for a in db.scalars(select(BlindActivity).where(BlindActivity.status == 'unblinding')):
        job = db.get(Job, a.sealed_job_id) if a.sealed_job_id else None
        if job is None:
            # 受理事务未能留下封存任务：回到已锁定状态，原候选保留，可重新受理
            a.status = 'locked'
            record(db, 'worker', 'blind.recovered', {'id': a.id, 'candidate': a.candidate_job_id, 'note': '揭盲中断，恢复原候选'})
        elif job.status == 'completed':
            finalize_unblind(db, a, job)
            record(db, 'worker', 'blind.unblinded', {'id': a.id, 'job': job.id, 'note': '中断恢复后补公布'})
        elif job.status == 'failed':
            fail_unblind(db, a, job.error)
            record(db, 'worker', 'blind.unblind_failed', {'id': a.id, 'job': job.id, 'error': a.error})
        # queued/running：running 已由通用恢复重置为 queued，继续等待执行即可


def counts(db, activity_id):
    rows = db.execute(select(BlindIncident.side, BlindIncident.state, func.count())
                      .where(BlindIncident.activity_id == activity_id)
                      .group_by(BlindIncident.side, BlindIncident.state)).all()
    out = {'open': 0, 'sealed': 0, 'accepted': 0, 'unblinded': 0}
    for side, state, n in rows:
        out[side] = out.get(side, 0) + n
        if state in ('accepted', 'unblinded'):
            out[state] = out.get(state, 0) + n
    return out
