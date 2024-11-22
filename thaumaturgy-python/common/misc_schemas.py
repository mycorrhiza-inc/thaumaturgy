from enum import Enum
from pydantic import BaseModel
from typing import Optional


class QueryData(BaseModel):
    match_name: Optional[str] = None
    match_source: Optional[str] = None
    match_doctype: Optional[str] = None
    match_stage: Optional[str] = None
    match_metadata: Optional[dict] = None


class KnownFileExtension(Enum, str):
    pdf = "pdf"
    docx = "docx"
    doc = "doc"
    xlsx = "xlsx"
    html = "html"
    md = "md"
    txt = "txt"
