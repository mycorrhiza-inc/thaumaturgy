from common.niclib import rand_string, rand_filepath

# Note: Refactoring imports.py


from typing import Optional


# from langchain.vectorstores import FAISS

import subprocess
import os


from pathlib import Path

from util.gpu_compute_calls import (
    GPUComputeEndpoint,
    audio_to_text_api,
    translate_text_api,
)

from util.file_io import S3FileManager

import yaml

from common.niclib import create_markdown_string, seperate_markdown_string


class MarkdownExtractor:
    # TODO : Plug this into the constant system and elimate tmpdir stuff if possible
    def __init__(self, logger, tmpdir: Path, priority: bool = True):
        self.tmpdir = tmpdir
        self.logger = logger
        self.priority = priority
        self.s3_client = S3FileManager(logger=self.logger)
        # TODO : Add database connection.

    async def convert_text_into_eng(self, file_text: str, lang: str):
        if lang in ["en", "eng", "english", None]:
            return file_text
        english_text = await translate_text_api(file_text, lang, "en")
        return english_text

    async def process_raw_document_into_untranslated_text_from_hash(
        self, hash: str, extension: str, lang: str, override_dir: Optional[Path] = None
    ) -> str:

        async def process_pdf(s3_uri: str) -> str:
            self.logger.info("processing pdf")
            return_string = await GPUComputeEndpoint(self.logger).transcribe_pdf_s3_uri(
                s3_uri, priority=self.priority
            )
            return return_string

        # Take a file with a path of path and a pandoc type of doctype and convert it to pandoc markdown and return the output as a string.
        # TODO: Make it so that you dont need to run sudo apt install pandoc for it to work, and it bundles with the pandoc python library
        def process_pandoc(filepath: Path, doctype: str) -> str:
            command = f"pandoc -f {doctype} {filepath}"
            process = subprocess.Popen(
                command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            output, error = process.communicate()
            output_str = output.decode()
            error_str = error.decode()
            if error_str:  # TODO : Debug this weird if statement
                raise Exception(f"Error running pandoc command: {error_str}")
            return output_str

        if extension == "pdf":
            s3_uri = self.s3_client.generate_s3_uri_from_hash(hash)
            if s3_uri is None:
                raise Exception("File Not Found")
            return await process_pdf(s3_uri)
        file_loc = self.s3_client.generate_local_filepath_from_hash(hash)
        if file_loc is None:
            raise Exception("File Not Found")

        if not os.path.isfile(file_loc):
            raise Exception("A document with that hash is not present")
        if extension == "md":
            with open(file_loc, "r") as file:
                data = file.read().rstrip()
                text, new_metadata = seperate_markdown_string(data)
                # Redundant due to it processing metadata upon ingest.
                # metadata.update(new_metadata)
                return text

        if extension in [
            "html",
            "doc",
            "docx",
            "tex",
            "epub",
            "odt",
            "rtf",
        ]:
            return process_pandoc(file_loc, extension)
        if extension == "tex":
            return process_pandoc(file_loc, "latex")
        if extension in ["mp3", "opus", "mkv"]:
            return_text = await audio_to_text_api(file_loc, lang)
            return return_text
        else:
            raise ValueError(
                f'Improper File Type, processing Failed with file extension: "{extension}"'
            )
