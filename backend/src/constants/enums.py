from enum import Enum
class Role(str, Enum):
    admin = 'admin'
    analyst = 'analyst'
    viewer = 'viewer'
class JobStatus(str, Enum):
    queued = 'queued'
    running = 'running'
    completed = 'completed'
    failed = 'failed'
class BlindStatus(str, Enum):
    tuning = 'tuning'                # 已划分，仅开放样本可调参
    locked = 'locked'                # 候选分析已锁定，参数不再变更
    unblinding = 'unblinding'        # 揭盲已受理，封存部分计算中
    unblind_failed = 'unblind_failed'  # 揭盲计算失败，可重试；事故不退回可用池
    unblinded = 'unblinded'          # 已揭盲并公布
class BlindSide(str, Enum):
    open = 'open'
    sealed = 'sealed'
class IncidentState(str, Enum):
    assigned = 'assigned'    # 已划分到某活动一侧
    accepted = 'accepted'    # 揭盲已受理，即使失败也不退回可用
    unblinded = 'unblinded'  # 已揭盲公布
