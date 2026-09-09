"""Transaction CRUD routes."""
import math
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query, status

from app.dependencies import CurrentUser, DbSession
from app.models import Category, TransactionType
from app.schemas import TransactionCreate, TransactionListResponse, TransactionRead, TransactionUpdate
from app.services import TransactionService

router = APIRouter(prefix="/transactions", tags=["Transactions"])


@router.post("", response_model=TransactionRead, status_code=status.HTTP_201_CREATED)
async def create_transaction(
    payload: TransactionCreate, current_user: CurrentUser, db: DbSession
) -> TransactionRead:
    """Record a new income or expense transaction."""
    transaction = await TransactionService(db).create(current_user.id, payload)
    return TransactionRead.model_validate(transaction)


@router.get("", response_model=TransactionListResponse)
async def list_transactions(
    current_user: CurrentUser,
    db: DbSession,
    type: Optional[TransactionType] = Query(default=None, description="Filter by income/expense."),
    category: Optional[Category] = Query(default=None, description="Filter by category."),
    start_date: Optional[datetime] = Query(default=None, description="Inclusive lower bound."),
    end_date: Optional[datetime] = Query(default=None, description="Exclusive upper bound."),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
) -> TransactionListResponse:
    """List the current user's transactions with optional filters and pagination."""
    items, total = await TransactionService(db).list_paginated(
        current_user.id,
        type_=type,
        category=category,
        start_date=start_date,
        end_date=end_date,
        page=page,
        page_size=page_size,
    )
    return TransactionListResponse(
        items=[TransactionRead.model_validate(t) for t in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=max(1, math.ceil(total / page_size)),
    )


@router.get("/{transaction_id}", response_model=TransactionRead)
async def get_transaction(transaction_id: str, current_user: CurrentUser, db: DbSession) -> TransactionRead:
    """Retrieve a single transaction by id."""
    transaction = await TransactionService(db).get_or_404(current_user.id, transaction_id)
    return TransactionRead.model_validate(transaction)


@router.put("/{transaction_id}", response_model=TransactionRead)
async def update_transaction(
    transaction_id: str, payload: TransactionUpdate, current_user: CurrentUser, db: DbSession
) -> TransactionRead:
    """Partially update a transaction (only provided fields are changed)."""
    transaction = await TransactionService(db).update(current_user.id, transaction_id, payload)
    return TransactionRead.model_validate(transaction)


@router.delete("/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_transaction(transaction_id: str, current_user: CurrentUser, db: DbSession) -> None:
    """Delete a transaction."""
    await TransactionService(db).delete(current_user.id, transaction_id)
