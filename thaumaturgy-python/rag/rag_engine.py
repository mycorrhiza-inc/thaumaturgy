from llama_index.llms.openai import OpenAI
from llama_index.core import PromptTemplate

from llama_index.core.retrievers import BaseRetriever
from llama_index.core.llms import LLM
from dataclasses import dataclass
from typing import Optional, List, Union, Any, Tuple

from logic.databaselogic import get_files_from_uuids
import nest_asyncio
import asyncio

from common.chat_schemas import ChatRole, KeChatMessage, sanitzie_chathistory_llamaindex
from rag.SemanticSplitter import split_by_max_tokensize
from rag.llamaindex import get_llm_from_model_str
from vecstore.search import search

import logging


from models.files import FileRepository, FileSchema, model_to_schema

from vecstore import search


from uuid import UUID

from advanced_alchemy.filters import SearchFilter, CollectionFilter

import re

from constants import lemon_text

qa_prompt = (
    lambda context_str: f"""
The following documents should be relevant to the conversation:
---------------------
{context_str}
---------------------
"""
)


generate_query_from_chat_history_prompt = "Please disregard all instructions and generate a query that could be used to search a vector database for relevant information. The query should capture the main topic or question being discussed in the chat. Please output the query as a string, using a format suitable for a vector database search (e.g. a natural language query or a set of keywords)."

"""
Stuff
Chat history: User: "I'm looking for a new phone. What are some good options?" Assistant: "What's your budget?" User: "Around $500" Assistant: "Okay, in that range you have options like the Samsung Galaxy A series or the Google Pixel 4a"

Example output: "Query: 'best phones under $500'"
"""

does_chat_need_query = 'Please determine if you need to query a vector database of relevant documents to answer the user. Answer with only a "yes" or "no".'

query_str = (
    "Can you tell me about results from RLHF using both model-based and"
    " human-based evaluation?"
)


default_logger = logging.getLogger(__name__)


def strip_links_and_tables(markdown_text):
    # Remove markdown links
    no_links = re.sub(r"\[.*?\]\(.*?\)", "", markdown_text)
    # Remove markdown tables
    no_tables = re.sub(r"\|.*?\|", "", no_links)
    return no_tables


async def convert_search_results_to_frontend_table(
    search_results: List[Any],
    files_repo: FileRepository,
    max_results: int = 10,
    include_text: bool = True,
):
    logger = default_logger
    res = search_results[0]
    res = res[:max_results]
    uuid_list = []
    text_list = []
    # TODO: Refactor for less checks and ugliness
    for result in res:
        logger.info(result)
        logger.info(result["entity"])
        uuid = UUID(result["entity"]["source_id"])
        uuid_list.append(uuid)
        if include_text:
            text_list.append(result["entity"]["text"])
            # text_list.append(lemon_text)
    file_models = await get_files_from_uuids(files_repo, uuid_list)
    file_results = list(map(model_to_schema, file_models))
    if include_text:
        for index in range(len(file_results)):
            file_results[index].display_text = text_list[index]

    return file_results


class KeRagEngine:
    def __init__(self, llm: Union[str, Any]) -> None:
        if llm == "":
            llm = None
        if llm is None:
            llm = "llama-405b"
        if isinstance(llm, str):
            llm = get_llm_from_model_str(llm)
        self.llm = llm

    async def achat(self, chat_history: Any) -> Any:
        llama_chat_history = sanitzie_chathistory_llamaindex(chat_history)
        response = await self.llm.achat(llama_chat_history)
        str_response = str(response)

        def remove_prefixes(input_string: str) -> str:
            prefixes = ["assistant: "]
            for prefix in prefixes:
                if input_string.startswith(prefix):
                    input_string = input_string[
                        len(prefix) :
                    ]  # 10 is the length of "assistant: "
            return input_string

        str_response = remove_prefixes(str_response)
        return KeChatMessage(role=ChatRole.assistant, content=str_response)

    async def summarize_single_chunk(self, markdown_text: str) -> str:
        summarize_prompt = "Make sure to provide a well researched summary of the text provided by the user, if it appears to be the summary of a larger document, just summarize the section provided."
        summarize_message = KeChatMessage(
            role=ChatRole.assistant, content=summarize_prompt
        )
        text_message = KeChatMessage(role=ChatRole.user, content=markdown_text)
        summary = await self.achat(
            sanitzie_chathistory_llamaindex([summarize_message, text_message])
        )
        return summary.content

    async def summarize_mapreduce(
        self, markdown_text: str, max_tokensize: int = 8096
    ) -> str:
        splits = split_by_max_tokensize(markdown_text, max_tokensize)
        if len(splits) == 1:
            return await self.summarize_single_chunk(markdown_text)
        summaries = await asyncio.gather(
            *[self.summarize_single_chunk(chunk) for chunk in splits]
        )
        coherence_prompt = "Please rewrite the following list of summaries of chunks of the document into a final summary of similar length that incorperates all the details present in the chunks"
        cohere_message = KeChatMessage(ChatRole.assistant, coherence_prompt)
        combined_summaries_prompt = KeChatMessage(ChatRole.user, "\n".join(summaries))
        final_summary = await self.achat([cohere_message, combined_summaries_prompt])
        return final_summary.content
