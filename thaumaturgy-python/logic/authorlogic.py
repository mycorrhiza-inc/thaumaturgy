from commom.llm_utils import KeLLMUtils

from typing import Union


class AuthorExtraction:
    def __init__(self, llm: Union[str, KeLLMUtils]) -> None:
        if isinstance(llm, str):
            self.llm = KeLLMUtils(llm)
        else:
            self.llm = llm
