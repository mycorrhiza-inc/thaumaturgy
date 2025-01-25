import aiohttp
import json
from pydantic import ValidationError
from scraping.nypuc_types import NYPUCDocketInfo, NYPUCFilingObject


async def reindex_all_conversations_from_postgres():
    # Initialize aiohttp session for making HTTP requests
    async with aiohttp.ClientSession() as session:
        page = 1
        for _ in range(10000):
            # Construct the URL with pagination parameters
            url = f"https://api.kessler.xyz/v2/public/conversations?page={page}"
            async with session.get(url) as response:
                # Check if the response is successful
                if response.status != 200:
                    print(f"Error fetching page {page}: HTTP status {response.status}")
                    break

                # Parse the JSON response
                try:
                    conversations = await response.json()
                except aiohttp.ContentTypeError as e:
                    print(f"Error parsing JSON for page {page}: {e}")
                    break

                # Check if the current page has no data
                if not isinstance(conversations, list) or len(conversations) == 0:
                    break

                # Process each conversation in the current page
                for conversation in conversations:
                    metadata_str = conversation.get("Metadata")
                    if not metadata_str:
                        continue  # Skip if metadata is missing

                    try:
                        # Parse the metadata JSON string
                        metadata = json.loads(metadata_str)
                    except json.JSONDecodeError as e:
                        print(
                            f"Invalid JSON in metadata for conversation {conversation.get('ID')}: {e}"
                        )
                        continue

                    try:
                        # Validate and create NYPUCDocketInfo object
                        docket_info = NYPUCDocketInfo(**metadata)
                    except ValidationError as e:
                        print(
                            f"Validation error for conversation {conversation.get('ID')}: {e}"
                        )
                        continue

                    # Enqueue the docket_info for processing
                    # Assuming an async task queue is set up elsewhere
                    await process_single_docket(docket_info)
                    # Alternatively, add to a task queue here if applicable

                # Move to the next page
                page += 1


async def process_single_docket(docket_info: NYPUCDocketInfo):
    # Example processing: log or handle the docket info
    print(f"Processing docket {docket_info.docket_id}")
    # Additional logic to process filings or other data can be added here
    # For example, fetch filings related to the docket and create NYPUCFilingObject instances
