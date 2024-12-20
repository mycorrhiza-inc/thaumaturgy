from pathlib import Path

from yaml import Mark


from common.niclib import rand_string


import requests
import logging

from typing import Optional, Any


import aiohttp
import asyncio

from pydantic import BaseModel

from constants import (
    MARKER_MAX_POLLS,
    MARKER_SECONDS_PER_POLL,
    OS_TMPDIR,
    DATALAB_API_KEY,
    MARKER_ENDPOINT_URL,
    OPENAI_API_KEY,
)


global_marker_server_urls = ["https://marker.kessler.xyz"]

default_logger = logging.getLogger(__name__)


async def audio_to_text_api(filepath: Path, source_lang: Optional[str]) -> str:
    # The API endpoint you will be hitting
    url = "https://api.openai.com/v1/audio/transcriptions"
    # Open the file in binary mode
    # Figure out way to do these http uploads async
    # Also use speaker diarization.
    with filepath.open("rb") as file:
        # Define the multipart/form-data payload
        files = {"file": (filepath.name, file, "application/octet-stream")}
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "multipart/form-data",
        }
        data = {"model": "whisper-1"}
        if source_lang is not None:
            data["language"] = source_lang

        # Make the POST request with files
        response = requests.post(url, headers=headers, files=files, data=data)
        # Raise an exception if the request was unsuccessful
        response.raise_for_status()

    # Parse the JSON response
    response_json = response.json()

    # Extract the translated text from the JSON response
    translated_text = response_json["text"]
    return translated_text


async def translate_text_api(
    doctext: str, source_lang: Optional[str], target_lang: str
) -> str:
    raise Exception("not implemented")
    url = f"hbs://translate.googleapis.com/language/translate/v2"
    payload = {
        "text": doctext,
        "source_lang": source_lang,
        "target_lang": target_lang,
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as response:
            response.raise_for_status()
            response_json = await response.json()
            text = response_json.get("text")
            return text


class GPUComputeEndpoint:
    def __init__(
        self,
        logger: Optional[Any] = None,
        marker_endpoint_url: str = MARKER_ENDPOINT_URL,
        legacy_endpoint_url: str = "https://depricated-url.com",
        datalab_api_key: str = DATALAB_API_KEY,
    ):
        if logger is None:
            logger = default_logger
        self.logger = logger
        self.marker_endpoint_url = marker_endpoint_url
        self.endpoint_url = legacy_endpoint_url
        self.datalab_api_key = datalab_api_key

    async def pull_marker_endpoint_for_response(
        self, request_check_url: str, max_polls: int, poll_wait: int
    ) -> str:
        async with aiohttp.ClientSession() as session:
            for polls in range(max_polls):
                await asyncio.sleep(poll_wait)
                async with session.get(request_check_url) as poll_response:
                    poll_data = await poll_response.json()
                    # self.logger.info(poll_data)
                    if poll_data["status"] == "complete":
                        text = poll_data["markdown"]
                        if text == "":
                            raise Exception("Got Empty String from Markdown Server.")
                        self.logger.info(
                            f"Processed document after {polls} polls with text: {text[0:50]}\n"
                        )
                        return poll_data["markdown"]
                    if poll_data["status"] == "error":
                        e = poll_data["error"]
                        self.logger.error(
                            f"Pdf server encountered an error after {polls} : {e}"
                        )
                        raise Exception(
                            f"Pdf server encountered an error after {polls} : {e}"
                        )
                    if poll_data["status"] != "processing":
                        raise ValueError(
                            f"PDF Processing Failed. Status was unrecognized {poll_data['status']} after {polls} polls."
                        )
            raise TimeoutError("Polling for marker API result timed out")

    async def transcribe_pdf_s3_uri(
        self, s3_uri: str, external_process: bool = False, priority: bool = True
    ) -> str:
        logger = default_logger
        if external_process:
            # TODO : Make it so that it downloads the s3_uri onto local then uploads it to external process.
            raise Exception("s3 uploads not supported with external processimg.")
        else:
            base_url = global_marker_server_urls[0]
            if priority:
                query_str = "?priority=true"
            else:
                query_str = "?priority=false"
            marker_url_endpoint = (
                base_url + "/api/v1/marker/direct_s3_url_upload" + query_str
            )

            data = {"s3_url": s3_uri}
            logger.info(data)
            # data = {"langs": "en", "force_ocr": "false", "paginate": "true"}
            async with aiohttp.ClientSession() as session:
                async with session.post(marker_url_endpoint, json=data) as response:
                    response_data = await response.json()
                    # await the json if async
                    request_check_url_leaf = response_data.get("request_check_url_leaf")

                    if request_check_url_leaf is None:
                        raise Exception(
                            "Failed to get request_check_url from marker API response"
                        )
                    request_check_url = base_url + request_check_url_leaf
                    self.logger.info(
                        f"Got response from marker server, polling to see when file is finished processing at url: {request_check_url}"
                    )
            assert (
                MARKER_MAX_POLLS is not None
            ), "MARKER_MAX_POLLS is None, consider defining it!"
            assert (
                MARKER_SECONDS_PER_POLL is not None
            ), "MARKER_SECONDS_PER_POLL is None, consider defining it!"
            return await self.pull_marker_endpoint_for_response(
                request_check_url=request_check_url,
                max_polls=MARKER_MAX_POLLS,
                poll_wait=3 + (MARKER_SECONDS_PER_POLL - 3) * int(not priority),
            )

    # Commenting out, we should never need  to use datalab.
    # async def transcribe_pdf_filepath(
    #     self,
    #     filepath: Path,
    #     external_process: bool = False,
    #     priority=True,
    # ) -> str:
    #     if external_process:
    #         url = "https://www.datalab.to/api/v1/marker"
    #         self.logger.info(
    #             "Calling datalab api with key beginning with"
    #             + self.datalab_api_key[0 : (len(self.datalab_api_key) // 5)]
    #         )
    #         headers = {"X-Api-Key": self.datalab_api_key}
    #
    #         with open(filepath, "rb") as file:
    #             files = {
    #                 "file": (filepath.name + ".pdf", file, "application/pdf"),
    #                 "paginate": (None, True),
    #             }
    #             # data = {"langs": "en", "force_ocr": "false", "paginate": "true"}
    #             with requests.post(url, files=files, headers=headers) as response:
    #                 response.raise_for_status()
    #                 # await the json if async
    #                 data = response.json()
    #                 request_check_url = data.get("request_check_url")
    #
    #                 if request_check_url is None:
    #                     raise Exception(
    #                         "Failed to get request_check_url from marker API response"
    #                     )
    #                 self.logger.info(
    #                     "Got response from marker server, polling to see when file is finished processing."
    #                 )
    #                 return await self.pull_marker_endpoint_for_response(
    #                     request_check_url=request_check_url,
    #                     max_polls=200,
    #                     poll_wait=3 + 57 * int(not priority),
    #                 )
    #     else:
    #         base_url = global_marker_server_urls[0]
    #         if priority:
    #             query_str = "?priority=true"
    #         else:
    #             query_str = "?priority=false"
    #         marker_url_endpoint = base_url + "/api/v1/marker" + query_str
    #
    #         with open(filepath, "rb") as file:
    #             files = {
    #                 "file": (filepath.name + ".pdf", file, "application/pdf"),
    #                 # "paginate": (None, True),
    #             }
    #             # data = {"langs": "en", "force_ocr": "false", "paginate": "true"}
    #             with requests.post(marker_url_endpoint, files=files) as response:
    #                 response.raise_for_status()
    #                 # await the json if async
    #                 data = response.json()
    #                 request_check_url_leaf = data.get("request_check_url_leaf")
    #
    #                 if request_check_url_leaf is None:
    #                     raise Exception(
    #                         "Failed to get request_check_url from marker API response"
    #                     )
    #                 request_check_url = base_url + request_check_url_leaf
    #                 self.logger.info(
    #                     f"Got response from marker server, polling to see when file is finished processing at url: {request_check_url}"
    #                 )
    #                 return await self.pull_marker_endpoint_for_response(
    #                     request_check_url=request_check_url,
    #                     max_polls=200,
    #                     poll_wait=3 + 57 * int(not priority),
    #                 )
