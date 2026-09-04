from pydantic import BaseModel

from app.schemas.finance import (
    FinanceSummaryResponse,
    FinancialTransactionResponse,
    MonthlyBudgetResponse,
)
from app.schemas.monobank import MonobankConnectionResponse
from app.schemas.wealth import (
    FinancialAccountResponse,
    NetWorthSnapshotResponse,
    SavingsContributionResponse,
    SavingsGoalResponse,
    WealthSummary,
)


class MoneyWorkspaceResponse(BaseModel):
    finance: FinanceSummaryResponse
    transactions: list[FinancialTransactionResponse]
    budgets: list[MonthlyBudgetResponse]
    wealth: WealthSummary
    accounts: list[FinancialAccountResponse]
    goals: list[SavingsGoalResponse]
    contributions: list[SavingsContributionResponse]
    snapshots: list[NetWorthSnapshotResponse]
    currencies: list[str]
    monobank: MonobankConnectionResponse
