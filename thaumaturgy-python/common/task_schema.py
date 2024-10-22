# This might not belong in common, but its where all the other schemas are, plus we also probably want to push these tasks to a db somewhere


from pydantic import BaseModel
import uuid
from typing import Optional, Any
from datetime import datetime
from enum import Enum


class TaskType(str, Enum):
    add_file = "add_file"
    process_existing_file = "process_existing_file"


class Task(BaseModel):
    id: uuid.UUID = uuid.uuid4()
    task_type: TaskType
    kwargs: dict
    created_at: datetime = datetime.now()
    updated_at: datetime | None = None
    error: str | None = None
    completed: bool = False
    obj: Any
