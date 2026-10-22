"""Profile REST contract and use-case mapping."""

from fastapi import APIRouter, Request

from fintrack_common.api import Result
from fintrack_core.finance import schemas as s
from fintrack_core.finance.domain import Data, require
from fintrack_core.finance.http import Key, Uow, command, result
from fintrack_core.finance.ports import ReadRepositories, Repositories

router = APIRouter(tags=["core profile"])


@router.get("/workspace-snapshot", response_model=Result[s.WorkspaceSnapshot])
def workspace_snapshot(request: Request, uow: Uow) -> Result[Data]:
    """One bounded scoped read avoids a fresh database connection for every history page."""

    def read(r: ReadRepositories) -> Data:
        profiles = r.profile.list(limit=1)
        profile = (
            profiles[0]
            if profiles
            else {
                "id": request.app.state.core_scope_id,
                "version": 1,
                "name": "Development user",
                "currency": "BDT",
                "timezone": "Asia/Dhaka",
                "onboarded": False,
                "goals": [],
                "preferences": {},
            }
        )
        data: Data = {"profile": profile}
        for key, maximum in [
            ("accounts", 1000),
            ("transactions", 10000),
            ("categories", 1000),
            ("groups", 1000),
            ("rules", 1000),
            ("recurring", 1000),
            ("observations", 20000),
        ]:
            rows = getattr(r, key).list(limit=maximum + 1)
            require(len(rows) <= maximum, f"Workspace {key} snapshot limit exceeded.")
            data[key] = rows
        return data

    return result(request, uow.read(read))


@router.get("/bootstrap")
def bootstrap(request: Request) -> Result[Data]:
    return result(
        request,
        {
            "mode": "development",
            "api_version": "core-v1",
            "policy_version": "dev-v1",
            "currencies": s.currency_registry(),
            "identity": "single server-owned development workspace",
            "features": [
                "accounts",
                "transactions",
                "categories",
                "rules",
                "budgets",
                "recurring",
                "reports",
            ],
        },
    )


@router.get("/me", response_model=Result[s.ProfileRead])
def me(request: Request, uow: Uow) -> Result[Data]:
    def read(r: ReadRepositories) -> Data:
        rows = r.profile.list(limit=1)
        return (
            rows[0]
            if rows
            else {
                "id": request.app.state.core_scope_id,
                "version": 1,
                "name": "Development user",
                "currency": "BDT",
                "timezone": "Asia/Dhaka",
                "onboarded": False,
                "goals": [],
                "preferences": {},
            }
        )

    return result(request, uow.read(read))


@router.patch("/me/profile", response_model=Result[s.ProfileRead])
def profile(request: Request, body: s.ProfileEdit, uow: Uow, key: Key) -> Result[Data]:
    data = body.model_dump(mode="json", exclude_unset=True)
    return command(
        request,
        uow,
        key,
        "profile.update",
        data,
        lambda r: r.profile.save(
            request.app.state.core_scope_id,
            body.expected_version,
            {k: v for k, v in data.items() if k != "expected_version"},
        ),
    )


@router.patch("/me/preferences", response_model=Result[s.ProfileRead])
def preferences(request: Request, body: s.PreferencesEdit, uow: Uow, key: Key) -> Result[Data]:
    data = body.model_dump(mode="json", exclude_unset=True)

    def update(r: Repositories) -> Data:
        current = r.profile.get(request.app.state.core_scope_id)
        changes = {k: v for k, v in data.items() if k != "expected_version"}
        return r.profile.save(
            current["id"],
            body.expected_version,
            {"preferences": {**current["preferences"], **changes}},
        )

    return command(request, uow, key, "profile.preferences", data, update)


@router.get("/health/ready")
def ready(request: Request, uow: Uow) -> Result[Data]:
    return result(request, uow.ready())
