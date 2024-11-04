# This might not belong in common, but its where all the other schemas are, plus we also probably want to push these tasks to a db somewhere


from pydantic import BaseModel
import uuid
from typing import List, Optional, Any
from datetime import datetime
from enum import Enum


from .file_schemas import CompleteFileSchema


class TaskType(str, Enum):
    add_file_scraper = "add_file_scraper"
    process_existing_file = "process_existing_file"


class DatabaseInteraction(str, Enum):
    none = "none"
    insert_later = "insert_later"
    update = "update"
    insert = "insert"
    insert_report_later = "insert_report_later"
    insert_report = "insert_report"
    update_report = "update_report"


class Task(BaseModel):
    id: uuid.UUID = uuid.uuid4()
    url: str = f"https://thaum.kessler.xyz/v1/status/"
    priority: bool = True
    database_interact: DatabaseInteraction
    task_type: TaskType
    table_name: str = ""
    kwargs: dict = {}
    created_at: datetime = datetime.now()
    updated_at: datetime = datetime.now()
    error: str = ""
    completed: bool = False
    success: bool = False
    followup_task_id: Optional[uuid.UUID] = None
    followup_task_url: Optional[str] = None
    obj: Any


class DocTextInfo(BaseModel):
    language: str
    text: str
    is_original_text: bool


class ScraperInfo(BaseModel):
    file_url: str = ""  # throw a get request at this url to get the file
    text: str = ""  # Or get the text content from this field
    hash: str = ""  # Or get the file corrosponding to this hash from s3
    name: str = ""
    published_date: str = ""
    internal_source_name: str = ""
    docket_id: str = ""
    author_individual: str = ""
    author_individual_email: str = ""
    author_organisation: str = ""
    file_class: str = ""  # Decision, Public Comment, etc
    file_type: str = ""  # PDF, DOCX, etc
    lang: str = ""  # defaults to "en" unless otherwise specified
    item_number: str = ""


class BulkProcessInfo(BaseModel):
    generate_report: bool = False
    report_id: str = ""
    database_interaction: DatabaseInteraction = (
        DatabaseInteraction.insert_later
    )  # change to insert, once updates actually work.
    override_scrape_info: ScraperInfo = ScraperInfo()


class BulkProcessSchema(BaseModel):
    scraper_info_list: List[ScraperInfo]
    bulk_info: BulkProcessInfo


def override_scraper_info(original: ScraperInfo, override: ScraperInfo) -> ScraperInfo:
    for k, v in override.model_dump().items():
        if v is not None or v != "":
            setattr(original, k, v)
    return original


def task_rectify(task: Task) -> Task:
    assert task.id != uuid.UUID(
        "00000000-0000-0000-0000-000000000000"
    ), "Task has a null UUID"
    task.updated_at = datetime.now()
    task.url = f"https://thaum.kessler.xyz/v1/status/{task.id}"
    return task


def create_task(
    obj: Any,
    priority: bool,
    database_interaction: DatabaseInteraction,
    kwargs: dict = {},
    task_type: Optional[TaskType] = None,
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
    task = Task(
        task_type=computed_task_type,
        kwargs=kwargs,
        priority=priority,
        obj=obj,
        database_interact=database_interaction,
    )
    # Sometimes the uuid's that are computed on each task are the same, so hopefully this recomputation reduces those allegedly impossible duplicates.
    task.id = uuid.uuid4()
    task = task_rectify(task)
    return task
