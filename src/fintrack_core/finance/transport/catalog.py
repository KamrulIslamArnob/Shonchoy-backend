"""Catalog REST contract and use-case mapping."""

from uuid import UUID

from fastapi import APIRouter, Request

from fintrack_common.api import Page, Result
from fintrack_core.finance import schemas as s
from fintrack_core.finance.application import catalog
from fintrack_core.finance.domain import Data
from fintrack_core.finance.http import Key, Limit, Uow, collection, command, result

router = APIRouter(tags=["core catalog"])


@router.post("/category-groups", response_model=Result[s.GroupRead], status_code=201)
def create_group(request: Request, body: s.GroupCreate, uow: Uow, key: Key) -> Result[Data]:
    data = body.model_dump()
    return command(request, uow, key, "groups.create", data, lambda r: r.groups.add(data))


@router.get("/category-groups", response_model=Result[Page[s.GroupRead]])
def group_list(
    request: Request, uow: Uow, limit: Limit = 50, cursor: UUID | None = None
) -> Result[Data]:
    return result(request, uow.read(lambda r: collection(r.groups, limit, cursor)))


@router.patch("/category-groups/{identifier}", response_model=Result[s.GroupRead])
def edit_group(
    request: Request, identifier: UUID, body: s.GroupEdit, uow: Uow, key: Key
) -> Result[Data]:
    data = body.model_dump(exclude_unset=True)
    return command(
        request,
        uow,
        key,
        f"groups.edit:{identifier}",
        data,
        lambda r: r.groups.save(
            str(identifier),
            body.expected_version,
            {k: v for k, v in data.items() if k != "expected_version"},
        ),
    )


@router.post("/categories", response_model=Result[s.CategoryRead], status_code=201)
def create_category(request: Request, body: s.CategoryCreate, uow: Uow, key: Key) -> Result[Data]:
    data = body.model_dump(mode="json")
    return command(
        request, uow, key, "categories.create", data, lambda r: catalog.category(r, data)
    )


@router.get("/categories", response_model=Result[Page[s.CategoryRead]])
def category_list(
    request: Request, uow: Uow, limit: Limit = 50, cursor: UUID | None = None
) -> Result[Data]:
    return result(request, uow.read(lambda r: collection(r.categories, limit, cursor)))


@router.patch("/categories/{identifier}", response_model=Result[s.CategoryRead])
def edit_category(
    request: Request, identifier: UUID, body: s.CategoryEdit, uow: Uow, key: Key
) -> Result[Data]:
    data = body.model_dump(mode="json", exclude_unset=True)
    return command(
        request,
        uow,
        key,
        f"categories.edit:{identifier}",
        data,
        lambda r: catalog.category(r, data, str(identifier)),
    )
