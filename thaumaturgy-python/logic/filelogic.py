from typing_extensions import Doc
from common.file_schemas import FileTextSchema
from common.niclib import download_file
from common.task_schema import Task, GolangUpdateDocumentInfo
from common.llm_utils import KeLLMUtils
import os
from pathlib import Path

from sqlalchemy import select

from pydantic import TypeAdapter

from uuid import UUID

from common.file_schemas import (
    FileSchema,
    DocumentStatus,
    docstatus_index,
)

from logic.docingest import DocumentIngester
from logic.extractmarkdown import MarkdownExtractor

from typing import Optional


# from routing.file_controller import QueryData

import json

from common.niclib import rand_string


from util.file_io import S3FileManager

# import base64

from constants import KESSLER_URL, OS_TMPDIR, OS_HASH_FILEDIR, OS_BACKUP_FILEDIR

import asyncio
import aiohttp


import logging

default_logger = logging.getLogger(__name__)


# class FileTextSchema(BaseModel):
#     file_id: UUID
#     is_original_text: bool
#     language: str
#     text: str

# class GolangUpdateDocumentInfo(BaseModel):
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
#


# class DocTextInfo(BaseModel):
#     language: str
#     text: str
#     is_original_text: bool
#
#
# class GolangUpdateDocumentInfo(BaseModel):
#     id: Optional[uuid.UUID] = None
#     url: str
#     doctype: str
#     lang: str
#     name: str
#     source: str
#     hash: str
#     mdata: dict[str, Any]
#     stage: str
#     summary: str
#     short_summary: str
#     private: bool
#     doc_texts: list[DocTextInfo]


async def does_exist_file_with_hash(hash: str) -> bool:
    raise Exception("Deduplication not implemented on server")
    url = f"{KESSLER_URL}/file/get-by-hash/{hash}"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            response_dict = await response.json()
    return bool(response_dict.get("exists"))


async def upsert_full_file_to_db(
    obj: GolangUpdateDocumentInfo, insert: bool
) -> GolangUpdateDocumentInfo:
    logger = default_logger
    # FIXME: Absolutely no clue why the ny is necessary, fix routing in traefik
    if insert:
        url = f"https://api.kessler.xyz/v2/public/files/insert"
    else:
        id = str(obj.id)
        url = f"https://api.kessler.xyz/v2/public/files/{id}"
    json_data = json.loads(obj.model_dump_json())
    for _ in range(5):
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=json_data) as response:
                response_code = response.status
                if response_code == 200:
                    try:
                        response_json = await response.json()
                        # Validate and cast to GolangUpdateDocumentInfo
                        logger.info("File uploaded to db")
                        logger.info(response_json)
                        golang_update_info = GolangUpdateDocumentInfo(**response_json)
                        return golang_update_info
                    except (ValueError, TypeError, KeyError) as e:
                        print(f"Failed to parse JSON: {e}")
                        raise Exception(f"Failed to parse JSON: {e}")
                logger.info(f"Response code: {response_code}")
                logger.info(f"Response body: {await response.text()}")
        await asyncio.sleep(10)
    raise Exception(
        "Tried 5 times to commit file to DB and failed. TODO: SAVE AND BACKUP THE FILE TO REDIS OR SOMETHING IF THIS FAILS."
    )


async def add_url_raw(
    file_url: str,
    metadata: dict,
    check_duplicate: bool = False,
) -> GolangUpdateDocumentInfo:
    download_dir = OS_TMPDIR / Path("downloads")
    result_path = await download_file(file_url, download_dir)
    doctype = metadata.get("doctype")
    if doctype is None or doctype == "":
        doctype = result_path.suffix.lstrip(".")
    return await add_file_raw(result_path, metadata, check_duplicate)


async def add_file_raw(
    tmp_filepath: Path,
    metadata: dict,
    check_duplicate: bool = False,
) -> GolangUpdateDocumentInfo:
    logger = default_logger
    docingest = DocumentIngester(logger)
    file_manager = S3FileManager(logger=logger)

    def validate_metadata_mutable(metadata: dict):
        if metadata.get("lang") is None or metadata.get("lang") == "":
            metadata["lang"] = "en"
        try:
            assert isinstance(metadata.get("title"), str)
            assert isinstance(metadata.get("doctype"), str)
            assert isinstance(metadata.get("lang"), str)
        except Exception:
            logger.error("Illformed Metadata please fix")
            logger.error(f"Title: {metadata.get('title')}")
            logger.error(f"Doctype: {metadata.get('doctype')}")
            logger.error(f"Lang: {metadata.get('title')}")
            raise Exception(
                "Metadata is illformed, this is likely an error in software, please submit a bug report."
            )
        else:
            logger.info("Title, Doctype and language successfully declared")

        if (metadata["doctype"])[0] == ".":
            metadata["doctype"] = (metadata["doctype"])[1:]
        if metadata.get("source") is None:
            metadata["source"] = "unknown"
        metadata["language"] = metadata["lang"]
        return metadata

    # This assignment shouldnt be necessary, but I hate mutating variable bugs.
    metadata = validate_metadata_mutable(metadata)

    logger.info("Attempting to save data to file")
    result = file_manager.save_filepath_to_hash(tmp_filepath, OS_HASH_FILEDIR)
    (filehash, filepath) = result

    os.remove(tmp_filepath)

    if check_duplicate:
        if does_exist_file_with_hash(filehash):
            raise Exception("File Already exists in DB, erroring out.")
    # FIXME: RENEABLE BACKUPS AT SOME POINT
    # file_manager.backup_metadata_to_hash(metadata, filehash)
    new_file = GolangUpdateDocumentInfo(
        id=UUID("00000000-0000-0000-0000-000000000000"),
        url="N/A",
        name=metadata.get("title", "") or "",
        doctype=metadata.get("doctype", "") or "",
        lang=metadata.get("lang", "") or "",
        source=metadata.get("source", "") or "",
        mdata=metadata,
        stage=(DocumentStatus.unprocessed).value,
        hash=filehash,
        summary="",
        short_summary="",
    )
    mock = True
    if mock:
        return new_file
    file_from_server = await upsert_full_file_to_db(new_file, insert=True)
    assert file_from_server.id != UUID("00000000-0000-0000-0000-000000000000")
    return file_from_server


async def fetch_full_file_from_server(file_id: UUID) -> GolangUpdateDocumentInfo:
    logger = default_logger
    logger.info("fetching full file from server")
    url = f"{KESSLER_URL}/api/v1/thaumaturgy/full_file/{file_id}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            converted_fileschema = GolangUpdateDocumentInfo(**await response.json())
    return converted_fileschema


async def process_fileid_raw(
    file_id_str: str,
    stop_at: Optional[DocumentStatus] = None,
    priority: bool = True,
):
    file_uuid = UUID(file_id_str)
    full_obj = await fetch_full_file_from_server(file_uuid)
    return await process_file_raw(full_obj, stop_at=stop_at, priority=priority)


async def process_file_raw(
    obj: Optional[GolangUpdateDocumentInfo],
    stop_at: Optional[DocumentStatus] = None,
    priority: bool = True,
):
    logger = default_logger
    if obj is None:
        raise Exception("You done fucked up, you forgot to pass in a file")
    hash = obj.hash
    if hash is None:
        raise Exception("You done fucked up, you forgot to pass in a hash")
    if obj.lang is None or obj.lang == "":
        raise Exception("You done fucked up, you forgot to pass in a language")

    if stop_at is None:
        stop_at = DocumentStatus.completed
    source_id = obj.id
    logger.info(type(obj))
    logger.info(obj)
    current_stage = DocumentStatus(obj.stage)
    llm = KeLLMUtils("llama-70b")  # M6yabe replace with something cheeper.
    logger.info(obj.doctype)
    mdextract = MarkdownExtractor(logger, OS_TMPDIR, priority=priority)
    file_manager = S3FileManager(logger=logger)
    text = {}
    text_list = []
    doc_metadata = obj.mdata
    # Move back to stage 1 after all files are in s3 to save bandwith
    file_path = file_manager.generate_local_filepath_from_hash(obj.hash)
    if file_path is None:
        raise Exception(f"File Must Not exist for hash {obj.hash}")

    # TODO: Replace with pydantic validation

    async def process_stage_one():
        # FIXME: Change to deriving the filepath from the uri.
        # This process might spit out new metadata that was embedded in the document, ignoring for now
        logger.info("Sending async request to pdf file.")
        processed_original_text = (
            await mdextract.process_raw_document_into_untranslated_text_from_hash(
                hash, doc_metadata
            )
        )[0]
        logger.info(
            f"Successfully processed original text: {
                processed_original_text[0:20]}"
        )
        # FIXME: We should probably come up with a better backup protocol then doing everything with hashes
        file_manager.backup_processed_text(
            processed_original_text, hash, doc_metadata, OS_BACKUP_FILEDIR
        )
        assert isinstance(processed_original_text, str)
        logger.info("Backed up markdown text")
        text_list.append(
            FileTextSchema(
                file_id=source_id,
                is_original_text=True,
                language=obj.lang,
                text=processed_original_text,
            )
        )
        if obj.lang == "en":
            # Write directly to the english text box if
            # original text is identical to save space.
            text["english_text"] = processed_original_text
            # Skip translation stage if text already english.
            return DocumentStatus.stage3
        else:
            text["original_text"] = processed_original_text
            return DocumentStatus.stage2

    # text conversion
    async def process_stage_two():
        if obj.lang != "en":
            try:
                text["english_text"] = mdextract.convert_text_into_eng(
                    text["original_text"], obj.lang
                )
                text_list.append(
                    FileTextSchema(
                        file_id=source_id,
                        is_original_text=False,
                        language="en",
                        text=text["english_text"],
                    )
                )
            except Exception as e:
                raise Exception(
                    "failure in stage 2: \ndocument was unable to be translated to english.",
                    e,
                )
        else:
            raise ValueError(
                "failure in stage 2: \n Code is in an unreachable state, a document cannot be english and not english",
            )
        return DocumentStatus.stage3

    # TODO: Replace with pydantic validation

    async def process_embeddings():
        logger.info("Adding Embeddings")
        url = KESSLER_URL + "/api/v1/thaumaturgy/insert_file_embeddings"
        json_data = {
            "hash": obj.hash,
            "id": str(obj.id),
            "metadata": json.dumps(obj.mdata),
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=json_data) as response:
                response_code = response.status
                response_data = await response.json()
                # await the json if async

                if response_data is None:
                    raise Exception("Response is bad")
                if response_code < 200 or response_code >= 300:
                    raise Exception(f"Bad response code: {response_code}")

        return DocumentStatus.embeddings_completed

    async def create_summary():
        long_summary = await llm.summarize_mapreduce(text["english_text"])
        obj.summary = long_summary
        short_sum_instruct = (
            "Take this long summary and condense it into a 1-2 sentance short summary."
        )
        short_summary = await llm.simple_instruct(
            content=long_summary, instruct=short_sum_instruct
        )
        obj.short_summary = short_summary

        return DocumentStatus.summarization_completed

        # await the json if async

    while True:
        if docstatus_index(current_stage) >= docstatus_index(stop_at):
            logger.info(current_stage.value)
            obj.stage = current_stage.value
            await upsert_full_file_to_db(obj, insert=False)
            return obj
        try:
            match current_stage:
                case DocumentStatus.unprocessed:
                    # Mark that an attempt to process the document starting at stage 1
                    current_stage = DocumentStatus.stage1
                case DocumentStatus.stage1:
                    current_stage = await process_stage_one()
                case DocumentStatus.stage2:
                    current_stage = await process_stage_two()
                case DocumentStatus.stage3:
                    current_stage = await create_summary()
                case DocumentStatus.summarization_completed:
                    current_stage = await process_embeddings()
                case _:
                    raise Exception(
                        "Document was incorrectly added to database, \
                        try readding it again.\
                    "
                    )
        except Exception as e:
            logger.error(
                f"Document errored out while processing stage: {current_stage.value}"
            )
            obj.stage = current_stage.value
            await upsert_full_file_to_db(obj, insert=False)
            raise e
