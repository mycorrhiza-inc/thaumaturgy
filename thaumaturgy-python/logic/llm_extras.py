from common.file_schemas import (
    CompleteFileSchema,
    FileGeneratedExtras,
    get_english_text_from_fileschema,
)
from common.llm_utils import KeLLMUtils, get_llm_from_model_str


class ExtraGenerator:
    def __init__(self):
        self.big_llm = KeLLMUtils(get_llm_from_model_str("llama-405b"))
        self.tiny_llm = KeLLMUtils(get_llm_from_model_str("llama-8b"))
        self.medium_llm = KeLLMUtils(get_llm_from_model_str("llama-70b"))

    async def generate_extra_from_file(
        self, file: CompleteFileSchema
    ) -> FileGeneratedExtras:
        english_text = get_english_text_from_fileschema(file)
        if english_text is None or english_text == "":
            raise Exception("No English Text found in file")

        doc_extras = FileGeneratedExtras()
        doc_extras.summary = await self.medium_llm.simple_summary_truncate(english_text)
        short_sum_instruct = (
            "Take this long summary and condense it into a 1-2 sentance short summary."
        )
        doc_extras.short_summary = await self.big_llm.simple_instruct(
            content=doc_extras.summary, instruct=short_sum_instruct
        )
        impressiveness_content = doc_extras.summary
        if len(english_text) < 3000:
            impressiveness_content = english_text
        impressiveness_instruct = ""
        doc_extras.impressiveness = await self.big_llm.score_two_step(
            content=impressiveness_content,
            score_instruction=impressiveness_instruct,
            renorm_score_val=10.0,
        )
        return doc_extras
