from typing_extensions import Doc
from common.file_schemas import FileSchemaFull
from vecstore.docprocess import add_document_to_db
import os
from pathlib import Path
from typing import Any

from sqlalchemy import select

from pydantic import TypeAdapter
from models.utils import PydanticBaseModel as BaseModel

from uuid import UUID

from models.files import (
    FileModel,
    FileRepository,
    FileSchema,
    FileSchemaWithText,
    provide_files_repo,
    DocumentStatus,
    docstatus_index,
    model_to_schema,
)

from logic.docingest import DocumentIngester
from logic.extractmarkdown import MarkdownExtractor

from typing import List, Optional, Dict


# from routing.file_controller import QueryData

import json

from util.niclib import rand_string


from util.file_io import S3FileManager

# import base64

from constants import KESSLER_URL, OS_TMPDIR, OS_HASH_FILEDIR, OS_BACKUP_FILEDIR

import asyncio
import aiohttp


async def add_file_raw(
    tmp_filepath: Path,
    metadata: dict,
    process: bool,  # Figure out how to pass in a boolean as a query paramater
    override_hash: bool,
    files_repo: FileRepository,
    logger: Any,
) -> FileSchema:
    docingest = DocumentIngester(logger)
    file_manager = S3FileManager(logger=logger)

    def validate_metadata_mutable(metadata: dict):
        if metadata.get("lang") is None:
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

    # NOTE: this is a dangeous query
    # NOTE: Nicole- Also this doesnt allow for files with the same hash to have different metadata,
    # Scrapping it is a good idea, it was designed to solve some issues I had during testing and adding the same dataset over and over
    # FIX: fix this to not allow for users to DOS files
    query = select(FileModel).where(FileModel.hash == filehash)

    duplicate_file_objects = await files_repo.session.execute(query)
    duplicate_file_obj = duplicate_file_objects.scalar()

    if override_hash is True and duplicate_file_obj is not None:
        try:
            await files_repo.delete(duplicate_file_obj.id)
        except Exception:
            pass
        duplicate_file_obj = None

    if duplicate_file_obj is None:
        file_manager.backup_metadata_to_hash(metadata, filehash)
        metadata_str = json.dumps(metadata)
        new_file = FileModel(
            url="N/A",
            name=metadata.get("title"),
            doctype=metadata.get("doctype"),
            lang=metadata.get("lang"),
            source=metadata.get("source"),
            mdata=metadata_str,
            stage=(DocumentStatus.unprocessed).value,
            hash=filehash,
            summary=None,
            short_summary=None,
        )
        logger.info("new file:{file}".format(file=new_file.to_dict()))
        new_file = await files_repo.add(new_file)
        logger.info("added file!~")
        await files_repo.session.commit()
        logger.info("commited file to DB")

    else:
        logger.info(type(duplicate_file_obj))
        logger.info(
            f"File with identical hash already exists in DB with uuid:\
            {duplicate_file_obj.id}"
        )
        new_file = duplicate_file_obj

    if process:
        logger.info("Processing File")
        # Removing the await here, SHOULD allow an instant return to the user, but also have python process the file in the background hopefully!
        # TODO : It doesnt work, for now its fine and also doesnt compete with the daemon for resources. Fix later
        # TODO : Add passthrough for low priority file processing with a daemon in the background
        # since this is a sync main thread call, give it priority
        await process_file_raw(new_file, files_repo, logger, None, True)

    return new_file


async def process_fileid_raw(
    file_id_str: str,
    files_repo: FileRepository,
    logger: Any,
    stop_at: Optional[DocumentStatus] = None,
    priority: bool = True,
):
    file_uuid = UUID(file_id_str)
    logger.info(file_uuid)
    obj = await files_repo.get(file_uuid)
    return await process_file_raw(
        obj, logger=logger, stop_at=stop_at, priority=priority
    )


async def process_file_raw(
    obj: Optional[FileSchemaFull],
    logger: Any,
    stop_at: Optional[DocumentStatus] = None,
    priority: bool = True,
):
    if obj is None:
        obj = FileSchemaFull(id=UUID())
    if obj.hash is None:
        raise Exception("You done fucked up, you forgot to pass in a hash")
    if obj.lang is None or obj.lang == "":
        raise Exception("You done fucked up, you forgot to pass in a language")

    if stop_at is None:
        stop_at = DocumentStatus.completed
    source_id = obj.id
    logger.info(type(obj))
    logger.info(obj)
    current_stage = DocumentStatus(obj.stage)
    logger.info(obj.doctype)
    mdextract = MarkdownExtractor(logger, OS_TMPDIR, priority=priority)
    file_manager = S3FileManager(logger=logger)
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
        hash = obj.hash
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
            processed_original_text, obj.hash, doc_metadata, OS_BACKUP_FILEDIR
        )
        assert isinstance(processed_original_text, str)
        logger.info("Backed up markdown text")
        if obj.lang == "en":
            # Write directly to the english text box if
            # original text is identical to save space.
            obj.english_text = processed_original_text
            # Skip translation stage if text already english.
            return DocumentStatus.stage3
        else:
            obj.original_text = processed_original_text
            return DocumentStatus.stage2

    # text conversion
    async def process_stage_two():
        if obj.lang != "en":
            try:
                processed_english_text = mdextract.convert_text_into_eng(
                    obj.original_text, obj.lang
                )
                obj.english_text = processed_english_text
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
            "metadata": json.loads(obj.mdata),
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
        raise Exception("Not Implemented: Summarization")
        return DocumentStatus.summarization_completed

    async def push_result_to_db() -> None:
        url = KESSLER_URL + "/api/v1/thaumaturgy/upsert_file"
        json_data = obj.dict()
        json_data["id"] = str(obj.id)
        for _ in range(5):
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=json_data) as response:
                    response_code = response.status
                    if response_code >= 200 and response_code < 300:
                        return None
            await asyncio.sleep(10)
        raise Exception(
            "Tried 5 times to commit file to DB and failed. TODO: SAVE AND BACKUP THE FILE TO REDIS OR SOMETHING IF THIS FAILS."
        )

        # await the json if async

    while True:
        if docstatus_index(current_stage) >= docstatus_index(stop_at):
            logger.info(current_stage.value)
            obj.stage = current_stage.value
            await push_result_to_db()
            return None
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
            await push_result_to_db()
            raise e
