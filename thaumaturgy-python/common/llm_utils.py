from pydantic import BaseModel


from common.niclib import token_split

from llama_index.core.llms import ChatMessage as LlamaChatMessage

from enum import Enum


from typing import Optional, List, Union, Any, Dict

import asyncio


import logging

from llama_index.llms.groq import Groq
from llama_index.llms.openai import OpenAI
from llama_index.llms.fireworks import Fireworks


from constants import OPENAI_API_KEY, OCTOAI_API_KEY, GROQ_API_KEY, FIREWORKS_API_KEY


class ModelName(Enum):
    llama_8b = "llama-8b"
    llama_70b = "llama-70b"
    llama_90b = "llama-90b"
    llama_405b = "llama-405b"
    gpt_4o = "gpt-4o"


def get_llm_from_model_name(model_name: Optional[ModelName]):
    if model_name is None:
        model_name = ModelName.llama_405b

    match model_name:
        case ModelName.llama_8b:
            return Groq(
                model="llama-3.1-8b-instant", request_timeout=60.0, api_key=GROQ_API_KEY
            )
        case ModelName.llama_90b:
            return Fireworks(
                model="accounts/fireworks/models/llama-v3p2-90b-vision-instruct",
                api_key=FIREWORKS_API_KEY,
            )
        case ModelName.llama_70b:
            return Fireworks(
                model="accounts/fireworks/models/llama-v3p1-70b-instruct",
                api_key=FIREWORKS_API_KEY,
            )
        case ModelName.llama_405b:
            return Fireworks(
                model="accounts/fireworks/models/llama-v3p1-405b-instruct",
                api_key=FIREWORKS_API_KEY,
            )
        case ModelName.gpt_4o:
            return OpenAI(model="gpt-4o", request_timeout=60.0, api_key=OPENAI_API_KEY)


def get_model_name_from_str(model_name_str: Optional[str]) -> ModelName:
    if model_name_str is None:
        return ModelName.llama_405b

    model_map = {
        "llama-8b": ModelName.llama_8b,
        "llama-3.1-8b-instant": ModelName.llama_8b,
        "llama-90b": ModelName.llama_90b,
        "llama3.2-90b": ModelName.llama_90b,
        "llama-3-90b": ModelName.llama_90b,
        "llama90b": ModelName.llama_90b,
        "llama70b": ModelName.llama_70b,
        "llama-70b": ModelName.llama_70b,
        "llama3-70b-8192": ModelName.llama_70b,
        "llama-3.1-70b-versatile": ModelName.llama_70b,
        "llama-405b": ModelName.llama_405b,
        "llama-3.1-405b-reasoning": ModelName.llama_405b,
        "gpt-4o": ModelName.gpt_4o,
    }

    if model_name_str not in model_map:
        raise Exception("Model String Invalid or Not Supported")

    return model_map[model_name_str]


valid_model_names = [
    "llama-8b",
    "llama-3.1-8b-instant",
    "llama-70b",
    "llama3-70b-8192",
    "llama-3.1-70b-versatile",
    "llama-405b",
    "llama-3.1-405b-reasoning",
    "gpt-4o",
]


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


class RAGChat(BaseModel):
    model: Optional[str] = None
    chat_history: List[Dict[str, str]]


class ChatRole(str, Enum):
    user = "user"
    system = "system"
    assistant = "assistant"


class KeChatMessage(BaseModel):
    content: str
    role: ChatRole


# Do something with the chat message validation maybe, probably not worth it
def sanitzie_chathistory_llamaindex(chat_history: List) -> List[LlamaChatMessage]:
    def sanitize_message(raw_message: Union[dict, KeChatMessage]) -> LlamaChatMessage:
        if isinstance(raw_message, KeChatMessage):
            raw_message = cm_to_dict(raw_message)
        return LlamaChatMessage(
            role=raw_message["role"], content=raw_message["content"]
        )

    return list(map(sanitize_message, chat_history))


def dict_to_cm(input_dict: Union[dict, KeChatMessage]) -> KeChatMessage:
    if isinstance(input_dict, KeChatMessage):
        return input_dict
    return KeChatMessage(
        content=input_dict["content"], role=ChatRole(input_dict["role"])
    )


def cm_to_dict(cm: KeChatMessage) -> Dict[str, str]:
    return {"content": cm.content, "role": cm.role.value}


def unvalidate_chat(chat_history: List[KeChatMessage]) -> List[Dict[str, str]]:
    return list(map(cm_to_dict, chat_history))


def validate_chat(chat_history: List[Dict[str, str]]) -> List[KeChatMessage]:
    return list(map(dict_to_cm, chat_history))


def force_conform_chat(chat_history: List[Dict[str, str]]) -> List[Dict[str, str]]:
    chat_history = list(chat_history)
    for chat in chat_history:
        if not chat.get("role") in ["user", "system", "assistant"]:
            chat["role"] = "system"
        if not isinstance(chat.get("message"), str):
            chat["message"] = str(chat.get("message"))
    return chat_history


class KeLLMUtils:
    def __init__(self, llm: Optional[ModelName], slow_retry: bool = False) -> None:
        llm_callable = get_llm_from_model_name(llm)
        self.llm = llm_callable
        self.request_tries = (
            1 + slow_retry * 2
        )  # Only try once if slow_retry is false, else try 3 times
        self.retry_timeout_seconds = 60

    async def achat(self, chat_history: Any) -> Any:
        logger = default_logger
        llama_chat_history = sanitzie_chathistory_llamaindex(chat_history)
        successful_request = False
        response = None
        for i in range(0, self.request_tries):
            try:
                response = await self.llm.achat(llama_chat_history)
            except Exception as e:
                logger.info(f"Encountered error during llm response {e}")
                if i == self.request_tries - 1:
                    raise e
                await asyncio.sleep(self.retry_timeout_seconds)
            else:
                break
        if response is None:
            raise Exception("LLM retried until it rturned ")

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

    async def simple_summary_truncate(
        self, content: str, truncate_chars: int = 5000
    ) -> str:
        if len(content) > truncate_chars + 1:
            content = content[:truncate_chars]
        history = [
            KeChatMessage(
                content="Please provide a summary of the following content",
                role=ChatRole.system,
            ),
            KeChatMessage(content=content, role=ChatRole.user),
            KeChatMessage(
                content="Now please summarize the content above, dont do anything else except return a detailed summary.",
                role=ChatRole.system,
            ),
        ]
        completion = await self.achat(history)
        return completion.content

    async def simple_instruct(self, content: str, instruct: str) -> str:
        history = [
            KeChatMessage(content=instruct, role=ChatRole.system),
            KeChatMessage(content=content, role=ChatRole.user),
        ]
        completion = await self.achat(history)
        return completion.content

    async def score_two_step(
        self, content: str, score_instruction: str, renorm_score_val: float = 1.0
    ) -> float:
        formatted_score_instruction = f"Please think about what score you want to give the content for the following instructions: {score_instruction}\n Please think out loud and provide a justification for what score it should recive."
        history = [
            KeChatMessage(
                content="Here is some content you should assign a score to according to the instructions given at the end",
                role=ChatRole.system,
            ),
            KeChatMessage(content=content, role=ChatRole.user),
            KeChatMessage(content=formatted_score_instruction, role=ChatRole.system),
        ]
        response = await self.achat(history)
        history.append(response)
        history.append(
            KeChatMessage(
                content="Now please provide a score, include nothing else in your response",
                role=ChatRole.user,
            )
        )
        response = await self.achat(history)
        score_val = float(response.content)
        return score_val / renorm_score_val

    async def boolean_two_step(self, content: str, yes_or_no_instruction: str) -> bool:
        formatted_score_instruction = f"Please think about what the answer to the following question should be: {yes_or_no_instruction}\n Please think out loud and provide a justification for what you should answer."
        history = [
            KeChatMessage(
                content="Here is some content you should give a yes or no answer to according to the instructions given at the end",
                role=ChatRole.system,
            ),
            KeChatMessage(content=content, role=ChatRole.user),
            KeChatMessage(content=formatted_score_instruction, role=ChatRole.system),
        ]
        response = await self.achat(history)
        history.append(response)
        history.append(
            KeChatMessage(
                content='Now please provide answer "yes" or "no" to the original question, include nothing else in your response',
                role=ChatRole.user,
            )
        )
        response = (await self.achat(history)).content
        if response == "yes":
            return True
        if response == "no":
            return False
        raise Exception(
            "Could not parse yes or no response from llm, TODO: Implement retry code"
        )

    async def split_and_apply_instructions(
        self,
        content: str,
        split_length: int,
        prior_instruction: Optional[str],
        post_instruction: Optional[str],
        split_type: str = "token",
    ) -> List[str]:
        # Replace with semantic splitter
        match split_type:
            case "token":
                chunk_str_list = token_split(content, split_length)
            case _:
                chunk_str_list = token_split(content, split_length)
        prior_prompt_list = []
        if prior_instruction is not None and prior_instruction != "":
            prior_prompt_list.append(
                KeChatMessage(content=prior_instruction, role=ChatRole.system)
            )
        post_prompt_list = []
        if post_instruction is not None and post_instruction != "":
            post_prompt_list.append(
                KeChatMessage(content=post_instruction, role=ChatRole.system)
            )

        async def clean_chunk(chunk: str) -> str:
            history = (
                prior_prompt_list
                + [KeChatMessage(content=chunk, role=ChatRole.user)]
                + post_prompt_list
            )
            completion = await self.llm.achat(history)
            return completion.content

        tasks = [clean_chunk(chunk) for chunk in chunk_str_list]
        results = await asyncio.gather(*tasks)
        return results

    async def summarize_mapreduce(
        self, markdown_text: str, max_tokensize: int = 8096
    ) -> str:
        summarize_instruction = "Make sure to provide a well researched summary of the text provided by the user, if it appears to be the summary of a larger document, just summarize the section provided."

        summaries = await self.split_and_apply_instructions(
            content=markdown_text,
            split_length=max_tokensize,
            prior_instruction=summarize_instruction,
            post_instruction=None,
            split_type="token",
        )

        coherence_prompt = "Please rewrite the following list of summaries of chunks of the document into a final summary of similar length that incorperates all the details present in the chunks"
        cohere_message = KeChatMessage(role=ChatRole.system, content=coherence_prompt)
        combined_summaries_prompt = KeChatMessage(
            role=ChatRole.user, content="\n".join(summaries)
        )
        final_summary = await self.achat([cohere_message, combined_summaries_prompt])
        return final_summary.content

    # Mostly legacy at this point, do not include in any refactoring.
    async def mapreduce_llm_instruction_across_string(
        self, content: str, chunk_size: int, instruction: str, join_str: str
    ) -> str:

        results = await self.split_and_apply_instructions(
            content=content,
            split_length=chunk_size,
            prior_instruction=instruction,
            post_instruction=None,
            split_type="token",
        )
        return join_str.join(results)
