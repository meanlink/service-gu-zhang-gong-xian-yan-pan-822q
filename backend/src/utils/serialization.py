import hashlib, json
def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
def dataset_dict(d):
    return {'id':d.id, 'name':d.name, 'source':d.source, 'rows':len(d.records), 'checksum':d.checksum, 'created_at':d.created_at}
def job_dict(j):
    return {k:getattr(j,k) for k in ['id','name','dataset_id','params','status','result','error','approved','blind_activity_id','blind_scope','created_at','finished_at']}
def blind_dict(a, counts=None, datasets=None, isolation=None):
    d = {k:getattr(a,k) for k in ['id','name','status','sealed_percent','dataset_ids','candidate_job_id','locked_params','sealed_job_id','error','created_at','locked_at','unblinded_at']}
    d['counts'] = counts or {}
    d['datasets'] = datasets or []
    d['isolation'] = isolation or []
    return d
def report_dict(r):
    return {k:getattr(r,k) for k in ['id','name','job_id','destination','interval_seconds','next_run','enabled']}
def delivery_dict(d):
    return {k:getattr(d,k) for k in ['id','report_id','created_at','checksum','filename','destination']}
