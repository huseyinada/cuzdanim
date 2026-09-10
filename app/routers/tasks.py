"""Görevler (to-do / reminders) routes — unrelated to money on purpose."""
from fastapi import APIRouter, Query, status

from app.dependencies import CurrentUser, DbSession
from app.schemas import TaskCreate, TaskRead, TaskUpdate
from app.services import TaskService

router = APIRouter(prefix="/tasks", tags=["Tasks"])


@router.get("", response_model=list[TaskRead])
async def list_tasks(
    current_user: CurrentUser,
    db: DbSession,
    include_done: bool = Query(default=True, description="Set false to hide completed tasks."),
) -> list[TaskRead]:
    tasks = await TaskService(db).list_for_user(current_user.id, include_done=include_done)
    return [TaskRead.model_validate(t) for t in tasks]


@router.post("", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
async def create_task(payload: TaskCreate, current_user: CurrentUser, db: DbSession) -> TaskRead:
    task = await TaskService(db).create(current_user.id, payload)
    return TaskRead.model_validate(task)


@router.patch("/{task_id}", response_model=TaskRead)
async def update_task(task_id: str, payload: TaskUpdate, current_user: CurrentUser, db: DbSession) -> TaskRead:
    task = await TaskService(db).update(current_user.id, task_id, payload)
    return TaskRead.model_validate(task)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: str, current_user: CurrentUser, db: DbSession) -> None:
    await TaskService(db).delete(current_user.id, task_id)
