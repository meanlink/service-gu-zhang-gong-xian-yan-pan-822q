from sqlalchemy import text
from src.config.database import Base, engine
from src import models
def migrate():
    Base.metadata.create_all(engine)
    # 老库增量列：jobs 增加盲验归属（create_all 不会修改已存在的表）
    with engine.begin() as conn:
        if engine.dialect.name == 'postgresql':
            conn.execute(text('ALTER TABLE jobs ADD COLUMN IF NOT EXISTS blind_activity_id INTEGER'))
            conn.execute(text('ALTER TABLE jobs ADD COLUMN IF NOT EXISTS blind_scope VARCHAR(10)'))
        elif engine.dialect.name == 'sqlite':
            cols = {row[1] for row in conn.execute(text('PRAGMA table_info(jobs)'))}
            if 'blind_activity_id' not in cols:
                conn.execute(text('ALTER TABLE jobs ADD COLUMN blind_activity_id INTEGER'))
            if 'blind_scope' not in cols:
                conn.execute(text('ALTER TABLE jobs ADD COLUMN blind_scope VARCHAR(10)'))
if __name__=='__main__':migrate()
