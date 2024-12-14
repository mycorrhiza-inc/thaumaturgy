from copy import copy
from hmac import new
import traceback
import uuid
from typing_extensions import Doc, Tuple
from common.file_schemas import (
    AuthorInformation,
    CompleteFileSchema,
    DocProcStage,
    FileTextSchema,
    PGStage,
    getListAuthors,
)
from common.misc_schemas import KnownFileExtension
from common.niclib import download_file
from common.task_schema import DatabaseInteraction, Task
from common.llm_utils import KeLLMUtils, ModelName
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
from logic.llm_extras import ExtraGenerator
from util.file_io import S3FileManager

# import base64

from constants import (
    KESSLER_API_URL,
    OS_TMPDIR,
    OS_HASH_FILEDIR,
    MOCK_DB_CONNECTION,
)

import asyncio
import aiohttp


import logging

from logic.file_validation import (
    validate_and_rectify_file_extension,
    validate_file_hash_vs_extension,
)

default_logger = logging.getLogger(__name__)


async def process_file_raw(
    obj: CompleteFileSchema,
    stop_at: Optional[DocumentStatus] = None,
    priority: bool = True,
) -> Tuple[Optional[str], CompleteFileSchema]:
    obj = CompleteFileSchema.model_validate(obj, strict=True)
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
    llm = KeLLMUtils(
        llm=ModelName.llama_70b, slow_retry=True
    )  # Maybe replace with something cheeper.
    extra_gen = ExtraGenerator()
    mdextract = MarkdownExtractor(logger, OS_TMPDIR, priority=priority)
    file_manager = S3FileManager(logger=logger)
    text = {}
    # Move back to stage 1 after all files are in s3 to save bandwith

    async def process_stage_handle_extension():
        valid_extension = None
        try:
            valid_extension = KnownFileExtension(obj.extension)
        except Exception as e:
            logger.error(
                f"Invalid File Extension, this should have never been insereted into the db, trying to fix now: {obj.extension}, {e}"
            )
            valid_extension, valid_extension_str = validate_and_rectify_file_extension(
                obj.extension
            )
        if valid_extension is None:
            raise Exception(
                f"Unable to get proper file extension even after trying to rectify, please fix: {obj.extension}"
            )
        valid_file, error = await validate_file_hash_vs_extension(hash, valid_extension)
        if not valid_file:
            obj.stage.ingest_error_msg = error
            obj.stage.skip_processing = True
            raise Exception(f"File does not match extension: {obj.extension}, {error}")

        obj.extension = valid_extension.value
        if valid_extension == KnownFileExtension.xlsx:
            #
            return DocumentStatus.completed
        # Every other file on the valid extension list can be processed to return stage 1
        return DocumentStatus.stage1

    # TODO: Replace with pydantic validation

    async def process_stage_one():
        # FIXME: Change to deriving the filepath from the uri.
        # This process might spit out new metadata that was embedded in the document, ignoring for now
        logger.info("Sending async request to pdf file.")
        try:
            processed_original_text = (
                await mdextract.process_raw_document_into_untranslated_text_from_hash(
                    hash=hash, lang=obj.lang, extension=obj.extension
                )
            )
        except Exception as e:
            e_str = str(e)
            if "format error" in e_str:
                obj.stage.skip_processing = True
            raise e
        logger.info(
            f"Successfully processed original text: {
                processed_original_text[0:50]}"
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

    async def create_llm_extras():
        # assert (
        #     False
        # ), "LLM Extras Deemed too expensive to do now. Consider at a later time once all documents are initally in."
        extras = await extra_gen.generate_extra_from_file(obj)
        obj.extra = extras

        return DocumentStatus.summarization_completed

        # await the json if async

    # Better then a while loop that might run forever, this loop should absolutely end after 1000 iterations
    for _ in range(0, 1000):
        if docstatus_index(current_stage) >= docstatus_index(stop_at):
            logger.info(current_stage.value)
            obj.stage = DocProcStage(
                pg_stage=PGStage.COMPLETED,
                processing_error_msg="",
                ingest_error_msg=obj.stage.ingest_error_msg,
                database_error_msg="",
                docproc_stage=current_stage,
                is_errored=False,
                is_completed=True,
            )
            return None, obj
        try:
            match current_stage:
                case DocumentStatus.unprocessed:
                    # Mark that an attempt to process the document starting at stage 1
                    # TODO: Add new stage for file validation, now just using unprocessed.
                    current_stage = await process_stage_handle_extension()
                case DocumentStatus.stage1:
                    current_stage = await process_stage_one()
                case DocumentStatus.stage2:
                    current_stage = await process_stage_two()
                case DocumentStatus.stage3:
                    current_stage = await create_llm_extras()
                case DocumentStatus.summarization_completed:
                    current_stage = await process_embeddings()
                case DocumentStatus.embeddings_completed:
                    current_stage = DocumentStatus.completed
                case _:
                    raise Exception(
                        "Document was incorrectly added to database, \
                        try readding it again.\
                    "
                    )
        except Exception as e:
            tb = traceback.format_exc()
            logger.error(f"Document errored out during {current_stage.value} : {e}")
            logger.error(tb)
            obj.stage = DocProcStage(
                pg_stage=PGStage.ERRORED,
                database_error_msg="",
                ingest_error_msg=obj.stage.ingest_error_msg,
                skip_processing=obj.stage.skip_processing,
                processing_error_msg="Encountered Processing Error: " + str(e),
                docproc_stage=current_stage,
                is_errored=True,
                is_completed=True,
            )
            return str(e), obj
    raise Exception(
        "Congradulations, encountered unreachable code after an infinite loop in processing a single document in file logic."
    )
