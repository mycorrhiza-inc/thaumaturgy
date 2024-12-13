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
    disable_ingest_if_hash: bool = False,
) -> Tuple[Optional[str], CompleteFileSchema]:
    download_dir = OS_TMPDIR / Path("downloads")
    result_path = await download_file(file_url, download_dir)
    doctype = file_obj.extension
    if doctype is None or doctype == "":
        file_obj.extension = result_path.suffix.lstrip(".")
    return await add_file_raw(
        tmp_filepath=result_path,
        file_obj=file_obj,
        disable_ingest_if_hash=disable_ingest_if_hash,
    )


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


async def add_file_raw(
    tmp_filepath: Path,
    file_obj: CompleteFileSchema,
    disable_ingest_if_hash: bool = False,
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
    result = await file_manager.save_filepath_to_hash_async(
        tmp_filepath, OS_HASH_FILEDIR
    )
    file_obj.hash = result.hash

    os.remove(tmp_filepath)
    if result.did_exist and disable_ingest_if_hash:
        return "file already exists", file_obj

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
