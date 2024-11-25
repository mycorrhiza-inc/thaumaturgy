from typing import Optional
from pydantic import BaseModel


class DaemonState(BaseModel):
    enabled: Optional[bool] = None
    insert_process_task_after_ingest: Optional[bool] = None
    insert_process_to_front_of_queue: Optional[bool] = None
    maximum_concurrent_cluster_tasks: Optional[int] = None
    disable_ingest_if_hash_identified: Optional[bool] = None


STARTUP_DAEMON_STATE = DaemonState(
    enabled=False,
    insert_process_task_after_ingest=True,
    insert_process_to_front_of_queue=False,
    maximum_concurrent_cluster_tasks=60,
    disable_ingest_if_hash_identified=False,
)


def validateAllValuesDefined(existing_state: DaemonState) -> bool:
    # all function is a folding AND operation over a list of bools.
    return all(
        getattr(existing_state, field_name) is not None
        for field_name in existing_state.model_fields.keys()
    )


def updateExistingState(
    existing_state: DaemonState, new_state: DaemonState
) -> DaemonState:
    for field_name in new_state.model_fields:
        new_value = getattr(new_state, field_name)
        if new_value is not None:
            setattr(existing_state, field_name, new_value)
    return existing_state
