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
    priority: bool
    task_type: TaskType
    kwargs: dict
    created_at: datetime = datetime.now()
    updated_at: datetime | None = None
    error: str | None = None
    completed: bool = False
    obj: Any


class DocTextInfo(BaseModel):
    language: str
    text: str
    is_original_text: bool


class GolangUpdateDocumentInfo(BaseModel):
    url: str
    doctype: str
    lang: str
    name: str
    source: str
    hash: str
    mdata: dict[str, Any]
    stage: str
    summary: str
    short_summary: str
    private: bool
    doc_texts: list[DocTextInfo]


def create_task(obj: Any, priority: bool, kwargs: dict) -> Optional[Task]:
    def determine_task_type(obj: Any) -> Optional[TaskType]:
        if isinstance(obj, GolangUpdateDocumentInfo):
            return TaskType.process_existing_file

        return None

    task_type = determine_task_type(obj)
    if task_type is None:
        return None
    return Task(task_type=task_type, kwargs=kwargs, priority=priority, obj=obj)
