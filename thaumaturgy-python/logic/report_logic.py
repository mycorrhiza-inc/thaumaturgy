from typing import List
from pydantic import BaseModel

from common.file_schemas import AuthorInformation, CompleteFileSchema
from common.task_schema import Task, TaskType

import yaml
import textwrap


class ReportSchema(BaseModel):
    object_list: List[CompleteFileSchema] = []
    report_str: str = ""


def display_author_info(author_list: List[AuthorInformation]) -> str:
    return "\n".join([f"Author: {author.author_name}" for author in author_list])


def generate_report_snippet_from_file(file_obj: CompleteFileSchema) -> str:
    mdata_yaml = yaml.dump(file_obj.mdata)
    return_str = textwrap.dedent(
        f"""\
        File: {file_obj.name}
        Impressiveness: {file_obj.extra.impressiveness}
        Short Summary: {file_obj.extra.short_summary}
        {display_author_info(file_obj.authors)}
        Long Summary: {file_obj.extra.summary}
        Metadata: {mdata_yaml}"""
    )
    return return_str


async def generate_report(
    metadata: dict,
    task_list: List[Task],
) -> ReportSchema:
    return_report = ReportSchema()

    def filter_func(task) -> bool:
        is_valid = task.task_type == TaskType.process_existing_file and isinstance(
            task.obj, CompleteFileSchema
        )
        is_successful = task.success and task.completed
        return is_valid and is_successful

    filtered_tasks = list(filter(filter_func, task_list))
    file_objs = [task.obj for task in filtered_tasks]
    file_objs.sort(key=lambda x: x.extras.impressiveness, reverse=True)
    return_report.object_list = file_objs

    return return_report
