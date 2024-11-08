from common.file_schemas import (
    CompleteFileSchema,
    FileGeneratedExtras,
    get_english_text_from_fileschema,
)
from common.llm_utils import KeLLMUtils, get_llm_from_model_str
import logging

default_logger = logging.getLogger(__name__)


class ExtraGenerator:
    def __init__(self):
        self.big_llm = KeLLMUtils(get_llm_from_model_str("llama-405b"))
        self.tiny_llm = KeLLMUtils(get_llm_from_model_str("llama-8b"))
        self.medium_llm = KeLLMUtils(get_llm_from_model_str("llama-70b"))
        self.logger = default_logger

    async def generate_extra_from_file(
        self, file: CompleteFileSchema
    ) -> FileGeneratedExtras:
        english_text = get_english_text_from_fileschema(file)
        assert english_text != "", "Tried to generate llm extras with no english text."
        if english_text is None or english_text == "":
            raise Exception("No English Text found in file")

        doc_extras = FileGeneratedExtras()
        try:
            doc_extras.summary = await self.medium_llm.simple_summary_truncate(
                english_text
            )
            short_sum_instruct = "Take this long summary and condense it into a 1-2 sentance short summary."
            doc_extras.short_summary = await self.big_llm.simple_instruct(
                content=doc_extras.summary, instruct=short_sum_instruct
            )
        except Exception as e:
            self.logger.error(f"Failed to generate summary: {e}")
        document_content_string = english_text
        if len(document_content_string) > 2000:
            assert (
                doc_extras.summary != ""
            ), "Cannot proceed with processing huge document without summary."
            document_content_string = (
                f"Document to long, here is a summary instead:\n{doc_extras.summary}"
            )

        try:
            impressiveness_instruct = "Award a score from 0-10 for how impressive the authorship behind this paper is in terms of credentials, and the persusasiveness and authority of the document itself, a result of 1 should be an anonomous author, with a relatively cursory overview, and a 10 should be an impressive thurough well resaerched document written by multiple authors from an extremely prestegious organization. (You can also choose any fractional number between 0 and 10, like 9.7, or 4.2)"
            doc_extras.impressiveness = await self.big_llm.score_two_step(
                content=document_content_string,
                score_instruction=impressiveness_instruct,
                renorm_score_val=10.0,
            )
        except Exception as e:
            self.logger.error(f"Failed to score impressiveness: {e}")
        try:
            purpose_instruct = "Describe the purpose of this document, and what the author is wishing to acomplish by writing it."
            doc_extras.purpose = await self.big_llm.simple_instruct(
                content=document_content_string, instruct=purpose_instruct
            )
        except Exception as e:
            self.logger.error(f"Failed calling llm to determine document purpose: {e}")

        try:
            private_matter_instruction = "Is this document concern most accurately described as a private matter between two organisations (individuals, corperations, the goverment), that would not have a broader impact on public policy. Or could the impacts reach out to a broader community and is a matter multiple parties are engaged in?"
        except Exception as e:
            self.logger.error(f"Failed to generate private matter: {e}")
        return doc_extras
