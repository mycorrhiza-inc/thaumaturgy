from commom.llm_utils import KeLLMUtils, KeChatMessage, ChatRole

from typing import Union

import json
from pydantic import BaseModel

# class ChatRole(str, Enum):
#     user = "user"
#     system = "system"
#     assistant = "assistant"
#
#
# class KeChatMessage(BaseModel):
#     content: str
#     role: ChatRole

example_author_json = """{
    "name" : "Paul Atreides",
    "educational_history": "Caladan University: Bachelor's in Political Science",
    "location": "Planet Caladan, House Atreides",
    "email": "paul.atreides@caladan.house",
    "phone": "+1234567890",
    "current_employment": "Duke of Caladan",
    "employment_history": "Mentat Intern at House Atreides"
}"""


class AuthorInformation(BaseModel):
    name: str = ""
    educational_history: str = ""
    location: str = ""
    email: str = ""
    phone: str = ""
    current_employment: str = ""
    employment_history: str = ""


class AuthorExtraction:
    def __init__(self, llm: Union[str, KeLLMUtils]) -> None:
        if isinstance(llm, str):
            self.llm = KeLLMUtils(llm)
        else:
            self.llm = llm
            # invoke with await self.llm.achat(messages : List[KeChatMessage])

    # write a function that will take in a string, and an author name. Then it will prompt an llm with a message to go through the document and return any possible information about the author, educational history, location, email, phone, place of current employment, employment history, etc.
    async def extract_author_info_from_chunk(
        self, document: str, author_name: str
    ) -> AuthorInformation:
        # Formulate initial query prompt
        query = (
            f"Given the following document, extract any information about the author '{author_name}', "
            "including educational history, location, email, phone, place of current employment, and employment history.\n\n"
            f"Document:\n{document}\n\n"
            "Please return your response as a pure json string with no extra formatting like so:\n",
            example_author_json,
        )

        # Create an initial chat message for the LLM
        messages = [KeChatMessage(role=ChatRole.user, content=query)]

        # Call the LLM's chat function to get the response
        response_text = (await self.llm.achat(messages)).content

        response_dict = json.loads(response_text)

        author_information = AuthorInformation(**response_dict)

        return author_information


class AscertainPurpose:
    def __init__(self, llm: Union[str, KeLLMUtils]) -> None:
        if isinstance(llm, str):
            self.llm = KeLLMUtils(llm)
        else:
            self.llm = llm
            # invoke with await self.llm.achat(messages : List[KeChatMessage])

    def get_purpose(self, document_text: str, author_info) -> str:
        return "I am interested in the purpose of this document."
