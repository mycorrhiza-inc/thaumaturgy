# This might not belong in common, but its where all the other schemas are, plus we also probably want to push these tasks to a db somewhere


from pydantic import BaseModel
import uuid
from typing import Optional, Any
from datetime import datetime, date
from enum import Enum


from .file_schemas import FileTextSchema, FileSchemaFull


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
    obj: Any


# class FileTextSchema(BaseModel):
#     file_id: UUID
#     is_original_text: bool
#     language: str
#     text: str

# class FileSchemaFull(BaseModel):
#     id: UUID
#     url: str | None = None
#     hash: str | None = None
#     doctype: str | None = None
#     lang: str | None = None
#     name: str | None = None
#     source: str | None = None
#     stage: str | None = None
#     short_summary: str | None = None
#     summary: str | None = None
#     organization_id: UUID | None = None
#     mdata: Dict[str, Any] = {}
#     texts: List[FileTextSchema] = []
#     authors: List[IndividualSchema] = []
#     organization: OrganizationSchema | None = None


class DocTextInfo(BaseModel):
    language: str
    text: str
    is_original_text: bool


class GolangUpdateDocumentInfo(BaseModel):
    id: uuid.UUID = uuid.UUID("00000000-0000-0000-0000-000000000000")
    url: str = ""
    doctype: str = ""
    lang: str = ""
    name: str = ""
    source: str = ""
    hash: str = ""
    mdata: dict[str, Any] = {}
    stage: str = ""
    summary: str = ""
    short_summary: str = ""
    private: bool = False
    doc_texts: list[DocTextInfo] = []


# def convert_file_schema_full_to_golang_update(
#     file_schema: FileSchemaFull,
# ) -> GolangUpdateDocumentInfo:
#     doc_texts = [
#         DocTextInfo(
#             language=text.language,
#             text=text.text,
#             is_original_text=text.is_original_text,
#         )
#         for text in file_schema.texts
#     ]
#
#     return GolangUpdateDocumentInfo(
#         id=file_schema.id or uuid.uuid4(),
#         url=file_schema.url or "",
#         doctype=file_schema.doctype or "",
#         lang=file_schema.lang or "",
#         name=file_schema.name or "",
#         source=file_schema.source or "",
#         hash=file_schema.hash or "",
#         mdata=file_schema.mdata,
#         stage=file_schema.stage or "",
#         summary=file_schema.summary or "",
#         short_summary=file_schema.short_summary or "",
#         private=False,  # Default value, adjust if there's a corresponding field
#         doc_texts=doc_texts,
#     )
#
#
# def convert_golang_update_to_file_schema_full(
#     golang_update: GolangUpdateDocumentInfo,
# ) -> FileSchemaFull:
#     texts = [
#         FileTextSchema(
#             file_id=golang_update.id,  # No equivalent, leave as None or adjust if necessary
#             is_original_text=text.is_original_text,
#             language=text.language,
#             text=text.text,
#         )
#         for text in golang_update.doc_texts
#     ]
#
#     return FileSchemaFull(
#         id=golang_update.id,  # No equivalent, leave as None or adjust if necessary
#         url=golang_update.url,
#         hash=golang_update.hash,
#         doctype=golang_update.doctype,
#         lang=golang_update.lang,
#         name=golang_update.name,
#         source=golang_update.source,
#         stage=golang_update.stage,
#         short_summary=golang_update.short_summary,
#         summary=golang_update.summary,
#         organization_id=None,  # No equivalent, leave as None or adjust if necessary
#         mdata=golang_update.mdata,
#         texts=texts,
#         authors=[],  # No equivalent, leave empty or adjust if necessary
#         organization=None,  # No equivalent, leave as None or adjust if necessary
#     )
#


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
    if id == uuid.UUID("00000000-0000-0000-0000-000000000000"):
        task.id = uuid.uuid4()
    task.updated_at = datetime.now()
    task.url = f"https://thaum.kessler.xyz/v1/status/{task.id}"
    return task


def create_task(
    obj: Any, priority: bool, kwargs: dict = {}, task_type: Optional[TaskType] = None
) -> Optional[Task]:
    def determine_task_type(obj: Any) -> Optional[TaskType]:
        if isinstance(obj, GolangUpdateDocumentInfo):
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
    task = task_rectify(task)
    return task
