import json
import traceback
from typing import Optional
from uuid import UUID
from pydantic import BaseModel

from pydantic import Field, field_validator, TypeAdapter

from typing import Any, Dict, List


from enum import Enum

from common.org_schemas import OrganizationSchema, IndividualSchema


import copy
import yaml


class FileTextSchema(BaseModel):
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
    skip_processing: bool = False
    is_errored: bool = False
    is_completed: bool = False
    ingest_error_msg: str = ""
    processing_error_msg: str = ""
    database_error_msg: str = ""


NEWDOCSTAGE = DocProcStage(
    pg_stage=PGStage.PENDING,
    docproc_stage=DocumentStatus.unprocessed,
    skip_processing=False,
    is_errored=False,
    is_completed=False,
)


class FileGeneratedExtras(BaseModel):
    summary: str = ""
    short_summary: str = ""
    purpose: str = ""
    impressiveness: float = 0.0


class AuthorInformation(BaseModel):
    author_id: UUID = UUID("00000000-0000-0000-0000-000000000000")
    author_name: str

    def display(self):
        return f"Author: {self.author_name}"


def getListAuthors(authorinfo_list: List[AuthorInformation]) -> List[str]:
    return [author.author_name for author in authorinfo_list]


class ConversationInformation(BaseModel):
    id: UUID = UUID("00000000-0000-0000-0000-000000000000")
    docket_id: str
    state: str


class CompleteFileSchema(BaseModel):
    id: UUID = UUID("00000000-0000-0000-0000-000000000000")
    verified: bool = False
    extension: str
    lang: str
    name: str
    hash: str
    is_private: bool
    mdata: Dict[str, Any]
    doc_texts: List[FileTextSchema] = []
    stage: DocProcStage = NEWDOCSTAGE
    extra: FileGeneratedExtras = FileGeneratedExtras()
    authors: List[AuthorInformation] = []
    conversation: ConversationInformation

    def display_llm_noextras_beyond_summary(self) -> str:
        metadata = self.display_trimmed_mdata()
        basic_data = f"Name:{self.name}\nLang:{self.lang}\nMetadata:\n{metadata}\nShort Summary: {self.extra.short_summary}"
        author_strings = "\n".join([author.display() for author in self.authors])
        text_data = f"Text:{get_english_text_from_fileschema(self)}"
        if len(text_data) > 3000:
            text_data = f"Document To Long, Providing truncated doc and summary\n Beginning of Document:{text_data[:500]}...\nSummary:{self.extra.summary}"
        return "\n".join([basic_data, author_strings, text_data])

    def display_trimmed_mdata(self) -> str:
        copied_mdata = copy.deepcopy(self.mdata)
        del copied_mdata["id"]
        del copied_mdata["uuid"]
        del copied_mdata["name"]
        del copied_mdata["lang"]
        del copied_mdata["hash"]
        del copied_mdata["stage"]
        del copied_mdata["authors"]
        output = yaml.dump(copied_mdata)
        return output


def get_english_text_from_fileschema(file: CompleteFileSchema) -> Optional[str]:
    texts = file.doc_texts
    for text in texts:
        if text.language == "en":
            return text.text
    return None


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
