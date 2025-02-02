import logging
from pathlib import Path
from typing import Tuple, Optional
from common.misc_schemas import KnownFileExtension
from util.file_io import S3FileManager
import magic
import chardet
import PyPDF2

default_logger = logging.getLogger(__name__)


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


async def validate_file_hash_vs_extension(
    filehash: str, extension: KnownFileExtension
) -> Tuple[bool, str]:
    logger = default_logger
    s3_client = S3FileManager()
    result_filepath = await s3_client.generate_local_filepath_from_hash_async(
        filehash, ensure_network=False, download_local=True
    )
    if result_filepath is None:
        logger.error(f"File Not Found for hash {filehash}")
        return False, "file not found"
    return await validate_file_path_vs_extension(result_filepath, extension)
    # Get MIME type


async def validate_file_path_vs_extension(
    filepath: Path, extension: KnownFileExtension
) -> Tuple[bool, str]:
    logger = default_logger

    def is_text_file(filepath: Path) -> bool:
        try:
            with open(filepath, "rb") as text_file:
                raw_data = text_file.read()
                raw_data.decode("utf-8")
            return True
        except Exception as e:
            default_logger.error(f"Invalid text file structure: {e}")
            return False

    try:
        mime = magic.Magic(mime=True)
        file_mime = mime.from_file(filepath)
        is_text = is_text_file(filepath)

        match extension:
            case KnownFileExtension.pdf:
                with open(filepath, "rb") as pdf_file:
                    header = pdf_file.read(4)
                    if header != b"%PDF":
                        logger.info(f"File with path {filepath} is a valid PDF")
                        return False, "not a valid pdf header"
                if is_text:
                    return False, "pdf is text file"
                if file_mime != "application/pdf":
                    logger.error(f"Invalid MIME type for PDF: {file_mime}")
                    return False, "invalid mime type for pdf"

                # # FIXME: This llm generated code will error out and cause random errors ince PyPDF2 is not thread safe.
                # # Some Unknown percentage of errors on the pdf processor are caused using this bug. But hopefully mime detection
                # # should stop the obvious downloaded the wrong file bugs.
                try:
                    with open(filepath, "rb") as pdf_file:
                        reader = PyPDF2.PdfReader(pdf_file)
                        # Just accessing num_pages will validate the PDF structure
                        _ = len(reader.pages)
                    return True, ""
                except Exception as e:
                    logger.error(f"Invalid PDF structure: {e}")
                    return False, "invalid pdf structure"
                logger.error("Unreachable code reached")
                return False, "unreachable code reached"

            case KnownFileExtension.xlsx:
                # Apparently xlsx files are actually text, who would have thunk it. XLSB are the binary versions.
                # if is_text:
                #     return False, "xlsx is text file"
                if (
                    file_mime
                    != "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                ):
                    logger.error(f"Invalid MIME type for XLSX: {file_mime}")
                    return False, "invalid mime type for xlsx"
                return True, ""

                # # Try to open and read the XLSX
                # try:
                #     workbook = openpyxl.load_workbook(result_filepath, read_only=True)
                #     workbook.close()
                #     return True
                # except Exception as e:
                #     logger.error(f"Invalid XLSX structure: {e}")
                #     return False

            case (
                KnownFileExtension.html | KnownFileExtension.md | KnownFileExtension.txt
            ):
                if not is_text:
                    return False, "text file is not a proper text encoding"
                # Check if it's a text file
                if not file_mime.startswith("text/"):
                    default_logger.error(f"Not a text file. MIME type: {file_mime}")
                    return False, "invalid mime type for text file"
                return True, ""

        logger.error("Unreachable code reached")
        return False, "encountered unreachable code"

    except Exception as e:
        default_logger.error(f"Error validating file: {e}")
        return False, f"error validating file: {e}"
