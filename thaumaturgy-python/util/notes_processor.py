from rag.rag_engine import KeRagEngine
from util.gpu_compute_calls import audio_to_text_api
from pydantic import BaseModel
from pathlib import Path
from uuid import UUID
from typing import Optional
from common.niclib import token_split


class TranscribedNote(BaseModel):
    id: UUID
    raw_transcript: Optional[str] = None
    clean_transcript: Optional[str] = None
    summary: Optional[str] = None

llm = KeRagEngine("llama70b")

async def process_note_task(
    filepath: Path, lang: Optional[str] = None
) -> TranscribedNote:
    CHUNK_SIZE = 500
    if lang is None:
        lang = "en"
    file_uuid = UUID()
    raw_transcript = await audio_to_text_api(filepath, lang)

    async def clean_transcript(raw_transcript: str) -> str:
        split = token_split(raw_transcript, CHUNK_SIZE)
        async def clean_chunk(c: str) -> str:

    result = TranscribedNote(id=file_uuid)
    return result
