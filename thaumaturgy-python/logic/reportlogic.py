from typing import List
from pydantic import BaseModel

from common.file_schemas import CompleteFileSchema
from common.task_schema import Task, TaskType


class ReportSchema(BaseModel):
    object_list: List[CompleteFileSchema] = []
    report_str: str = ""


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
