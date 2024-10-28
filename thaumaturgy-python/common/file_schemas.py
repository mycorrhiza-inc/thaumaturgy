import json
import traceback
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
    error_msg: str = ""
    error_stacktrace: str = ""


NEWDOCSTAGE = DocProcStage(
    pg_stage=PGStage.PENDING,
    docproc_stage=DocumentStatus.unprocessed,
    is_errored=False,
    is_completed=False,
)


class FileGeneratedExtras(BaseModel):
    summary: str = ""
    short_summary: str = ""
    purpose: str = ""


class AuthorInformation(BaseModel):
    author_id: UUID = UUID("00000000-0000-0000-0000-000000000000")
    author_name: str


class FileMetadataSchema(BaseModel):
    json_obj: bytes = b""


class CompleteFileSchema(BaseModel):
    id: UUID
    extension: str
    lang: str
    name: str
    hash: str
    is_private: bool
    mdata: FileMetadataSchema
    doc_texts: List[FileTextSchema] = []
    stage: DocProcStage = NEWDOCSTAGE
    extra: FileGeneratedExtras = FileGeneratedExtras()
    authors: List[AuthorInformation] = []


def mdata_dict_to_object(mdata_dict: dict) -> FileMetadataSchema:
    try:
        json_data = json.dumps(mdata_dict)
        mdata_obj = FileMetadataSchema(json_obj=bytes(json_data, "utf-8"))
        return mdata_obj
    except Exception as e:
        tb = traceback.format_exc()
        error_string = f"Encountered error converting metadata to json: {e}"
        traceback_string = f"{tb}"
        return_dict = {"error": error_string, "traceback": traceback_string}
        error_json_obj = json.dumps(return_dict)
        error_mdata_obj = FileMetadataSchema(json_obj=bytes(error_json_obj, "utf-8"))
        return error_mdata_obj


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
