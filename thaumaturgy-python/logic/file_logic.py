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

default_logger = logging.getLogger(__name__)


async def does_exist_file_with_hash(hash: str) -> bool:
    raise Exception("Deduplication not implemented on server")

    # async with aiohttp.ClientSession() as session:
    #     async with session.get(url) as response:
    #         response_dict = await response.json()
    # return bool(response_dict.get("exists"))


async def upsert_full_file_to_db(
    obj: CompleteFileSchema, interact: DatabaseInteraction
) -> CompleteFileSchema:
    obj = CompleteFileSchema.model_validate(obj, strict=True)
    if MOCK_DB_CONNECTION:
        return obj
    logger = default_logger
    original_id = copy(obj.id)
    if interact == DatabaseInteraction.insert:
        url = f"{KESSLER_API_URL}/v2/public/files/insert"
    elif interact == DatabaseInteraction.update:
        assert isinstance(obj.id, UUID)
        assert obj.id != UUID(
            "00000000-0000-0000-0000-000000000000"
        ), "Cannot update a file with a null uuid"
        id_str = str(obj.id)
        url = f"{KESSLER_API_URL}/v2/public/files/{id_str}/update"
        logger.info(f"Hitting file update endpoint: {url}")
    else:
        return obj
    json_data_string = obj.model_dump_json()
    logger.info(json_data_string)
    # for _ in range(3):
    errors = []
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
                if interact == DatabaseInteraction.insert:
                    assert (
                        id != original_id
                    ), "Identical ID returned from the server, this should be impossible if you are inserting a file."
                obj.id = id
                return obj
            errorstring = f"Response URL: {url}\nTruncated Response Data: {json_data_string[:200]}\nResponse code: {response_code}\nResponse body: {await response.text()}"
            logger.error(errorstring)
            errors.append(errorstring)
    raise Exception(
        f"Tried to commit file to DB and failed. TODO: SAVE AND BACKUP THE FILE TO REDIS OR SOMETHING IF THIS FAILS. Encountered errors:\n{str(errors)}"
    )


async def add_url_raw(
    file_url: str,
    file_obj: CompleteFileSchema,
    check_duplicate: bool = False,
) -> Tuple[Optional[str], CompleteFileSchema]:
    download_dir = OS_TMPDIR / Path("downloads")
    result_path = await download_file(file_url, download_dir)
    doctype = file_obj.extension
    if doctype is None or doctype == "":
        file_obj.extension = result_path.suffix.lstrip(".")
    return await add_file_raw(result_path, file_obj, check_duplicate)


async def split_author_field_into_authordata(
    author_str: str, llm: KeLLMUtils
) -> List[AuthorInformation]:
    logger = default_logger
    if author_str == "":
        return []
    # If string has no commas return the string as a singleton author information, not implementing since it might be a ny specific thing.

    # Use LLMs to split out the code for stuff relating to the thing.
    command = 'Take the list of organisations and return a json list of the authors like so ["Organisation 1", "Organization 2, Inc"]. Dont return anything except a json parsable list.'
    try:
        json_authorlist = await llm.simple_instruct(author_str, command)
        if json_authorlist in ["", "{}", "[]"]:
            raise Exception(
                "Returned an empty author list dispite author data being included."
            )

        author_list = json.loads(json_authorlist)
        if author_list is None or author_list == []:
            raise Exception(
                "Returned an empty author list dispite author data being included."
            )
    except Exception as e:
        logger.error(
            f'LLM encountered some error or produced unparsable data, splitting on "," as a backup: {e}',
        )
        author_list = author_str.split(",")

    author_info_list = [
        AuthorInformation(
            author_id=UUID("00000000-0000-0000-0000-000000000000"),
            author_name=author,
        )
        for author in author_list
    ]
    return author_info_list


def validate_and_rectify_file_extension(
    raw_extension: str,
) -> Tuple[Optional[KnownFileExtension], str]:
    logger = default_logger
    raw_extension = raw_extension.strip()
    raw_extension = raw_extension.lower()

    # Handle extensions with file size like "pdf (148 KB)"
    if "(" in raw_extension:
        raw_extension = raw_extension.split("(")[0].strip()

    try:
        extension = KnownFileExtension(raw_extension)
        return extension, raw_extension
    except Exception as e:
        logger.error(
            f"Could not validate extension: {raw_extension}, raised error: {e}"
        )
        return None, raw_extension


async def add_file_raw(
    tmp_filepath: Path,
    file_obj: CompleteFileSchema,
    check_duplicate: bool = False,
) -> Tuple[Optional[str], CompleteFileSchema]:
    logger = default_logger
    file_manager = S3FileManager(logger=logger)
    # This step doesnt need anything super sophisticated, and also has contingecnices for failed requests, so retries are kinda unecessary
    small_llm = KeLLMUtils(
        ModelName.llama_70b, slow_retry=False
    )  # Replace with something bigger, got bad results with splitting the author fields

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
    file_obj.mdata = validate_metadata_mutable(file_obj.mdata)

    logger.info("Attempting to save data to file")
    result = file_manager.save_filepath_to_hash(tmp_filepath, OS_HASH_FILEDIR)
    (filehash, filepath) = result
    file_obj.hash = filehash

    os.remove(tmp_filepath)

    if check_duplicate:
        if does_exist_file_with_hash(filehash):
            raise Exception("File Already exists in DB, erroring out.")
    # FIXME: RENEABLE BACKUPS AT SOME POINT
    # file_manager.backup_metadata_to_hash(metadata, filehash)
    author_names = file_obj.mdata.get("author")
    if author_names is None:
        author_names = file_obj.mdata.get("authors")
    if author_names is None:
        author_names = ""

    # TODO: Add examples to this prompt for better author splitting results.
    authors_info = await split_author_field_into_authordata(author_names, small_llm)
    file_obj.authors = authors_info
    authors_strings = getListAuthors(authors_info)
    file_obj.mdata["authors"] = authors_strings

    return None, file_obj


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
    file_path = file_manager.generate_local_filepath_from_hash(obj.hash)
    if file_path is None:
        raise Exception(f"File Must Not exist for hash {obj.hash}")

    def process_stage_handle_extension():
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
        processed_original_text = (
            await mdextract.process_raw_document_into_untranslated_text_from_hash(
                hash=hash, lang=obj.lang, extension=obj.extension
            )
        )
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
        assert (
            False
        ), "LLM Extras Deemed too expensive to do now. Consider at a later time once all documents are initally in."
        extras = await extra_gen.generate_extra_from_file(obj)
        obj.extra = extras

        return DocumentStatus.summarization_completed

        # await the json if async

    # Better then a while loop that might run forever, this loop should absolutely end after 1000 iterations
    for i in range(0, 1000):
        if docstatus_index(current_stage) >= docstatus_index(stop_at):
            logger.info(current_stage.value)
            obj.stage = DocProcStage(
                pg_stage=PGStage.COMPLETED,
                processing_error_msg="",
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
                    current_stage = process_stage_handle_extension()
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
                processing_error_msg="Encountered Processing Error: " + str(e),
                docproc_stage=current_stage,
                is_errored=True,
                is_completed=True,
            )
            return str(e), obj
    raise Exception(
        "Congradulations, encountered unreachable code after an infinite loop in processing a single document in file logic."
    )
