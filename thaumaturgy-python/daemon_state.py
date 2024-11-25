from typing import Optional
from pydantic import BaseModel


class DaemonState(BaseModel):
    enabled: Optional[bool] = None
    insert_process_task_after_ingest: Optional[bool] = None
    insert_process_to_front_of_queue: Optional[bool] = None


STARTUP_DAEMON_STATE = DaemonState(
    enabled=False,
    insert_process_task_after_ingest=True,
    insert_process_to_front_of_queue=False,
)


def validateAllValuesDefined(existing_state: DaemonState) -> bool:
    if existing_state.enabled is None:
        return False
    if existing_state.insert_process_task_after_ingest is None:
        return False
    if existing_state.insert_process_to_front_of_queue is None:
        return False
    return True


def updateExistingState(existing_state: DaemonState, new_state: DaemonState):
    if new_state.enabled is not None:
        existing_state.enabled = new_state.enabled
    if new_state.insert_process_task_after_ingest is not None:
        existing_state.insert_process_task_after_ingest = (
            new_state.insert_process_task_after_ingest
        )
    if new_state.insert_process_to_front_of_queue is not None:
        existing_state.insert_process_to_front_of_queue = (
            new_state.insert_process_to_front_of_queue
        )
    return existing_state
