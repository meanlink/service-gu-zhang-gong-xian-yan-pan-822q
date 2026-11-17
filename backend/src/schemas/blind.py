from pydantic import BaseModel, Field
class BlindInput(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    dataset_ids: list[int] = Field(min_length=1, max_length=20)
    sealed_percent: int = Field(default=40, ge=10, le=90)
class LockInput(BaseModel):
    job_id: int
