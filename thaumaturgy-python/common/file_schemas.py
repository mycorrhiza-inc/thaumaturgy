from uuid import UUID
from pydantic import BaseModel

from pydantic import Field, field_validator, TypeAdapter

from typing import Annotated, Any, List, Dict, Optional


from enum import Enum

from common.org_schemas import OrganizationSchema, IndividualSchema


class FileTextSchema(BaseModel):
    file_id: UUID
    is_original_text: bool
    language: str
    text: str


class PGStage(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    ERRORED = "errored"


class DocumentStatus(str, Enum):
    unprocessed = "unprocessed"
    completed = "completed"
    encounters_analyzed = "encounters_analyzed"
    organization_assigned = "organization_assigned"
    summarization_completed = "summarization_completed"
    embeddings_completed = "embeddings_completed"
    upload_document_to_db = "upload_document_to_db"
    stage3 = "stage3"
    stage2 = "stage2"
    stage1 = "stage1"


class DocProcStage(BaseModel):
    pg_stage: PGStage
    docproc_stage: DocumentStatus
    is_errored: bool
    is_completed: bool
    error_msg: Optional[str] = None
    error_stacktrace: Optional[str] = None


class FileGeneratedExtras(BaseModel):
    summary: Optional[str] = None
    short_summary: Optional[str] = None
    purpose: Optional[str] = None


class FileMetadataSchema(BaseModel):
    json_obj: bytes


class CompleteFileSchema(BaseModel):
    id: UUID
    extension: str
    lang: str
    name: str
    hash: str
    is_private: bool
    mdata: FileMetadataSchema
    doc_texts: List[FileTextSchema]
    stage: DocProcStage
    extra: FileGeneratedExtras


# I am deeply sorry for not reading the python documentation ahead of time and storing the stage of processed strings instead of ints, hopefully this can atone for my mistakes


# This should probably be a method on documentstatus, but I dont want to fuck around with it for now
def docstatus_index(docstatus: DocumentStatus) -> int:
    match docstatus:
        case DocumentStatus.unprocessed:
            return 0
        case DocumentStatus.stage1:
            return 1
        case DocumentStatus.stage2:
            return 2
        case DocumentStatus.stage3:
            return 3
        case DocumentStatus.summarization_completed:
            return 4
        case DocumentStatus.embeddings_completed:
            return 5
        case DocumentStatus.organization_assigned:
            return 6
        case DocumentStatus.encounters_analyzed:
            return 7
        case DocumentStatus.upload_document_to_db:
            return 8
        case DocumentStatus.completed:
            return 1000
