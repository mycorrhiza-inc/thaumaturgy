from common.chat_schemas import ChatRole, KeChatMessage
from rag.rag_engine import KeRagEngine
from util.gpu_compute_calls import audio_to_text_api
from pydantic import BaseModel
from pathlib import Path
from uuid import UUID
from typing import Optional
from common.niclib import token_split
import asyncio


class TranscribedNote(BaseModel):
    id: UUID
    raw_transcript: Optional[str] = None
    clean_transcript: Optional[str] = None
    summary: Optional[str] = None


llm = KeRagEngine("llama70b")


async def process_note_task(
    filepath: Path, lang: Optional[str] = None
) -> TranscribedNote:
    TRANSCRIPT_CHUNK_SIZE = 1024
    NOTE_CHUNK_SIZE = 2048
    if lang is None:
        lang = "en"
    file_uuid = UUID()
    raw_transcript = await audio_to_text_api(filepath, lang)

    async def clean_transcript_proc(raw_transcript: str) -> str:
        split = token_split(raw_transcript, NOTE_CHUNK_SIZE)

        async def clean_chunk(chunk: str) -> str:
            clean_chunk_prompt = "You are a transcription cleanup robot. Please take in the chunk of transcript provided by the user, and return a version of the transcript that doesnt have any repeated phrases, umms, ahhs or sentance fragments. DO NOT SUMMARIZE THE TRANSCRIPT. Try to match every word verbatim except when cleaning the sentances. Don't say anything to the user other then providing the cleaned transcript."

            history = [
                KeChatMessage(content=clean_chunk_prompt, role=ChatRole.assistant),
                KeChatMessage(content=chunk, role=ChatRole.user),
            ]
            completion = await llm.achat(history)
            return completion.content

        tasks = [clean_chunk(chunk) for chunk in split]
        results = await asyncio.gather(*tasks)
        return "".join(results)

    test = "Test"
    clean_transcript = await clean_transcript_proc(raw_transcript)
    result = TranscribedNote(
        id=file_uuid, raw_transcript=raw_transcript, clean_transcript=clean_transcript
    )
    return result
