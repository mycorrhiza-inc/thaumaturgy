# This might not belong in common, but its where all the other schemas are, plus we also probably want to push these tasks to a db somewhere


from pydantic import BaseModel
import uuid
from typing import Optional, Any
from datetime import datetime, date
from enum import Enum


from .file_schemas import CompleteFileSchema, FileTextSchema, FileSchemaFull


class TaskType(str, Enum):
    add_file_scraper = "add_file_scraper"
    process_existing_file = "process_existing_file"


class Task(BaseModel):
    id: uuid.UUID = uuid.uuid4()
    url: str = f"https://thaum.kessler.xyz/v1/status/"
    priority: bool = True
    task_type: TaskType
    table_name: str = ""
    kwargs: dict = {}
    created_at: datetime = datetime.now()
    updated_at: datetime = datetime.now()
    error: str | None = None
    completed: bool = False
    success: bool = False
    followup_task_id: Optional[uuid.UUID] = None
    followup_task_url: Optional[str] = None
    obj: Any


class DocTextInfo(BaseModel):
    language: str
    text: str
    is_original_text: bool


# class GolangUpdateDocumentInfo(BaseModel):
#     id: uuid.UUID = uuid.UUID("00000000-0000-0000-0000-000000000000")
#     url: str = ""
#     doctype: str = ""
#     lang: str = ""
#     name: str = ""
#     source: str = ""
#     hash: str = ""
#     mdata: dict[str, Any] = {}
#     stage: str = ""
#     summary: str = ""
#     short_summary: str = ""
#     private: bool = False
#     doc_texts: list[DocTextInfo] = []


class ScraperInfo(BaseModel):
    file_url: str  # throw a get request at this url to get the file
    name: str = ""
    published_date: str = ""
    internal_source_name: str = ""
    docket_id: str = ""
    author_organisation: str = ""
    file_class: str = ""  # Decision, Public Comment, etc
    file_type: str = ""  # PDF, DOCX, etc
    lang: str = ""  # defaults to "en" unless otherwise specified
    item_number: str = ""


def task_rectify(task: Task) -> Task:
    assert task.id != uuid.UUID(
        "00000000-0000-0000-0000-000000000000"
    ), "Task has a null UUID"
    task.updated_at = datetime.now()
    task.url = f"https://thaum.kessler.xyz/v1/status/{task.id}"
    return task


def create_task(
    obj: Any, priority: bool, kwargs: dict = {}, task_type: Optional[TaskType] = None
) -> Optional[Task]:
    def determine_task_type(obj: Any) -> Optional[TaskType]:
        if isinstance(obj, CompleteFileSchema):
            return TaskType.process_existing_file
        if isinstance(obj, ScraperInfo):
            return TaskType.add_file_scraper

        return None

    computed_task_type = determine_task_type(obj)
    if task_type is not None:
        assert computed_task_type == task_type
    if computed_task_type is None:
        return None
    task = Task(task_type=computed_task_type, kwargs=kwargs, priority=priority, obj=obj)
    # Sometimes the uuid's that are computed on each task are the same, so hopefully this recomputation reduces those allegedly impossible duplicates.
    task.id = uuid.uuid4()
    task = task_rectify(task)
    return task
