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
    # Moving this to another file might be a good idea. Plus throwing the semantic splitter to split on sentnaces is probably a good idea.
    async def mapreduce_llm_instruction_across_string(
        content: str, chunk_size: int, instruction: str, join_str: str
    ) -> str:
        split = token_split(content, chunk_size)

        async def clean_chunk(chunk: str) -> str:

            history = [
                KeChatMessage(content=instruction, role=ChatRole.assistant),
                KeChatMessage(content=chunk, role=ChatRole.user),
            ]
            completion = await llm.achat(history)
            return completion.content

        tasks = [clean_chunk(chunk) for chunk in split]
        results = await asyncio.gather(*tasks)
        return join_str.join(results)

    TRANSCRIPT_CHUNK_SIZE = 1024
    NOTE_CHUNK_SIZE = 4096
    if lang is None:
        lang = "en"
    file_uuid = UUID()
    raw_transcript = await audio_to_text_api(filepath, lang)
    clean_chunk_prompt = "You are a transcription cleanup robot. Please take in the chunk of transcript provided by the user, and return a version of the transcript that doesnt have any repeated phrases, umms, ahhs or sentance fragments. DO NOT SUMMARIZE THE TRANSCRIPT. Try to match every word verbatim except when cleaning the sentances. Don't say anything to the user other then providing the cleaned transcript."

    clean_transcript = await mapreduce_llm_instruction_across_string(
        content=raw_transcript,
        chunk_size=NOTE_CHUNK_SIZE,
        instruction=clean_chunk_prompt,
        join_str="",
    )
    create_notes_prompt = "You are a note taking assistant. Please take in the transcript provided by the user and return detailed notes that outlines the key points of the discussion. Make sure to take note of anything the group came to concensus on, any items on the agenda for the meeting and any action items that the group decided to take."
    notes = await mapreduce_llm_instruction_across_string(
        content=clean_transcript,
        chunk_size=NOTE_CHUNK_SIZE,
        instruction=create_notes_prompt,
        join_str="\n",
    )
    result = TranscribedNote(
        id=file_uuid,
        raw_transcript=raw_transcript,
        clean_transcript=clean_transcript,
        notes=notes,
    )

    return result
