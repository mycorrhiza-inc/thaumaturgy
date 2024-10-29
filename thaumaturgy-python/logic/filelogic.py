from copy import copy
import traceback
import uuid
from typing_extensions import Doc
from common.file_schemas import (
    AuthorInformation,
    CompleteFileSchema,
    DocProcStage,
    FileMetadataSchema,
    FileTextSchema,
    PGStage,
    mdata_dict_to_object,
)
from common.niclib import download_file
from common.task_schema import Task
from common.llm_utils import KeLLMUtils
import os
from pathlib import Path

from sqlalchemy import select

from pydantic import TypeAdapter, model_validator

from uuid import UUID

from common.file_schemas import (
    DocumentStatus,
    docstatus_index,
)

from logic.extractmarkdown import MarkdownExtractor

from typing import List, Optional


# from routing.file_controller import QueryData

import json

from common.niclib import rand_string


from util.file_io import S3FileManager

# import base64

from constants import (
    KESSLER_API_URL,
    OS_TMPDIR,
    OS_HASH_FILEDIR,
    OS_BACKUP_FILEDIR,
    MOCK_DB_CONNECTION,
)

import asyncio
import aiohttp


import logging

default_logger = logging.getLogger(__name__)


async def does_exist_file_with_hash(hash: str) -> bool:
    raise Exception("Deduplication not implemented on server")

    # async with aiohttp.ClientSession() as session:
    #     async with session.get(url) as response:
    #         response_dict = await response.json()
    # return bool(response_dict.get("exists"))


async def upsert_full_file_to_db(
    obj: CompleteFileSchema, insert: bool
) -> CompleteFileSchema:
    obj = CompleteFileSchema.model_validate(obj, strict=True)
    if MOCK_DB_CONNECTION:
        return obj
    logger = default_logger
    original_id = copy(obj.id)
    if insert:
        url = f"https://api.kessler.xyz/v2/public/files/insert"
    else:
        assert isinstance(obj.id, UUID)
        assert obj.id != UUID(
            "00000000-0000-0000-0000-000000000000"
        ), "Cannot update a file with a null uuid"
        id_str = str(obj.id)
        url = f"https://api.kessler.xyz/v2/public/files/{id_str}"
        logger.info(f"Hitting file update endpoint: {url}")
    json_data_string = obj.model_dump_json()
    logger.info(json_data_string)
    for _ in range(3):
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=json_data_string) as response:
                response_code = response.status
                if response_code == 200:
                    try:
                        response_json = await response.json()
                        # Validate and cast to CompleteFileSchema
                        logger.info("File uploaded to db")
                        logger.info(response_json)
                    except (ValueError, TypeError, KeyError) as e:
                        print(f"Failed to parse JSON: {e}")
                        raise Exception(f"Failed to parse JSON: {e}")
                    id_str = response_json.get("id")
                    if id_str is None:
                        print(f"No id returned from the server")
                        raise Exception(f"No id returned from the server")
                    try:
                        id = UUID(id_str)
                    except Exception as e:
                        print(f"Failed to parse UUID: {e}")
                        raise Exception(f"Failed to parse UUID: {e}")

                    assert id != UUID(
                        "00000000-0000-0000-0000-000000000000"
                    ), "Got Back null uuid from server."
                    if insert:
                        assert (
                            id != original_id
                        ), "Identical ID returned from the server, this should be impossible if you are inserting a file."
                    obj.id = id
                    return obj
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
) -> CompleteFileSchema:
    download_dir = OS_TMPDIR / Path("downloads")
    result_path = await download_file(file_url, download_dir)
    doctype = metadata.get("extension")
    if doctype is None or doctype == "":
        doctype = result_path.suffix.lstrip(".")
    return await add_file_raw(result_path, metadata, check_duplicate)


async def add_file_raw(
    tmp_filepath: Path,
    metadata: dict,
    check_duplicate: bool = False,
) -> CompleteFileSchema:
    logger = default_logger
    file_manager = S3FileManager(logger=logger)

    def split_author_field_into_authordata(author_str: str) -> List[AuthorInformation]:
        if author_str == "":
            return []
        # Use LLMs to split out the code for stuff relating to the thing.
        author_list = [author.strip() for author in author_str.split(",")]
        author_info_list = [
            AuthorInformation(
                author_id=UUID("00000000-0000-0000-0000-000000000000"),
                author_name=author,
            )
            for author in author_list
        ]
        return author_info_list

    def validate_metadata_mutable(metadata: dict):
        if metadata.get("lang") is None or metadata.get("lang") == "":
            metadata["lang"] = "en"
        try:
            assert isinstance(metadata.get("title"), str)
            assert isinstance(metadata.get("extension"), str)
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

        if (metadata["extension"])[0] == ".":
            metadata["extension"] = (metadata["extension"])[1:]
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
    new_file = CompleteFileSchema(
        id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
        name=metadata.get("title", "") or "",
        extension=metadata.get("extension", "") or "",
        lang=metadata.get("lang", "") or "",
        hash=filehash,
        authors=split_author_field_into_authordata(metadata.get("authors", "")),
        mdata=mdata_dict_to_object(metadata),
        is_private=False,
    )
    file_from_server = await upsert_full_file_to_db(new_file, insert=True)
    assert isinstance(file_from_server.id, UUID)
    assert file_from_server.id != UUID(
        "00000000-0000-0000-0000-000000000000"
    ), "File has a null UUID"
    return file_from_server


async def process_file_raw(
    obj: CompleteFileSchema,
    stop_at: Optional[DocumentStatus] = None,
    priority: bool = True,
):
    obj = CompleteFileSchema.model_validate(obj, strict=True)
    assert obj.id != UUID("00000000-0000-0000-0000-000000000000")
    logger = default_logger
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
    current_stage = DocumentStatus(obj.stage.docproc_stage)
    llm = KeLLMUtils("llama-70b")  # M6yabe replace with something cheeper.
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
                hash=hash, lang=obj.lang, extension=obj.extension
            )
        )[0]
        logger.info(
            f"Successfully processed original text: {
                processed_original_text[0:20]}"
        )
        assert isinstance(processed_original_text, str)
        assert processed_original_text != "", "Got Back Empty Processed Text"
        logger.info("Backed up markdown text")
        obj.doc_texts.append(
            FileTextSchema(
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
                text["english_text"] = await mdextract.convert_text_into_eng(
                    text["original_text"], obj.lang
                )
                obj.doc_texts.append(
                    FileTextSchema(
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
        # TODO : Automate processing of embeddings
        # logger.info("Adding Embeddings")
        # url = KESSLER_URL + "/api/v1/thaumaturgy/insert_file_embeddings"
        # json_data = {
        #     "hash": obj.hash,
        #     "id": str(obj.id),
        #     "metadata": json.dumps(obj.mdata),
        # }
        # async with aiohttp.ClientSession() as session:
        #     async with session.post(url, json=json_data) as response:
        #         response_code = response.status
        #         response_data = await response.json()
        #         # await the json if async
        #
        #         if response_data is None:
        #             raise Exception("Response is bad")
        #         if response_code < 200 or response_code >= 300:
        #             raise Exception(f"Bad response code: {response_code}")

        return DocumentStatus.embeddings_completed

    async def create_summary():
        assert text["english_text"] != "", "Cannot Summarize Empty Text"
        long_summary = await llm.simple_summary_truncate(text["english_text"])
        obj.extra.summary = long_summary
        short_sum_instruct = (
            "Take this long summary and condense it into a 1-2 sentance short summary."
        )
        short_summary = await llm.simple_instruct(
            content=long_summary, instruct=short_sum_instruct
        )
        obj.extra.short_summary = short_summary

        return DocumentStatus.summarization_completed

        # await the json if async

    while True:
        if docstatus_index(current_stage) >= docstatus_index(stop_at):
            logger.info(current_stage.value)
            obj.stage = DocProcStage(
                pg_stage=PGStage.COMPLETED,
                error_msg="",
                error_stacktrace="",
                docproc_stage=current_stage,
                is_errored=True,
                is_completed=True,
            )
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
            tb = traceback.format_exc()
            logger.error(
                f"Document errored out while processing stage: {current_stage.value}"
            )
            obj.stage = DocProcStage(
                pg_stage=PGStage.ERRORED,
                error_msg=str(e),
                error_stacktrace=str(tb),
                docproc_stage=current_stage,
                is_errored=True,
                is_completed=True,
            )
            await upsert_full_file_to_db(obj, insert=False)
            raise e
