from typing import List
from pydantic import BaseModel


class FileScrapeNYPUCInfo(BaseModel):
    serial: str
    date_filed: str
    nypuc_doctype: str
    name: str
    url: str
    organization: str
    itemNo: str
    file_name: str
    docket_id: str


class NYPUCFilingObject(BaseModel):
    case: str
    filings: List[FileScrapeNYPUCInfo]


class NYPUCDocketInfo(BaseModel):
    docket_id: str  # 24-C-0663
    matter_type: str  # Complaint
    matter_subtype: str  # Appeal of an Informal Hearing Decision
    industry_affected: str
    title: str  # In the Matter of the Rules and Regulations of the Public Service
    organization: str  # Individual
    date_filed: str  # 12/13/2022
