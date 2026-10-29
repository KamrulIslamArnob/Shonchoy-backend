"""Application interfaces; concrete repositories are composed per resource."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from fintrack_core.finance.domain import Data


class Reader(Protocol):
    def get(self, identifier: str) -> Data: ...
    def list(
        self, *, limit: int = 100, cursor: str | None = None, filters: Data | None = None
    ) -> list[Data]: ...


class Repository(Reader, Protocol):
    def add(self, values: Data) -> Data: ...
    def save(self, identifier: str, version: int, changes: Data) -> Data: ...


class LedgerReader(Protocol):
    def cashflow(self, month: str, currency: str) -> Data: ...
    def balances(self, currency: str) -> Data: ...
    def summary(self, month: str, currency: str) -> Data: ...
    def visible_transactions(self, start: str, end: str, currency: str) -> list[Data]: ...


@dataclass(frozen=True)
class ReadRepositories:
    accounts: Reader
    observations: Reader
    categories: Reader
    groups: Reader
    transactions: Reader
    rules: Reader
    budgets: Reader
    recurring: Reader
    profile: Reader
    ledger: LedgerReader


@dataclass(frozen=True)
class Repositories(ReadRepositories):
    accounts: Repository
    observations: Repository
    categories: Repository
    groups: Repository
    transactions: Repository
    rules: Repository
    budgets: Repository
    recurring: Repository
    profile: Repository


class UnitOfWork(Protocol):
    def ready(self) -> Data: ...
    def command(
        self, key: str, operation: str, payload: Data, action: Callable[[Repositories], Data]
    ) -> Data: ...
    def read(self, action: Callable[[ReadRepositories], Data]) -> Data: ...
