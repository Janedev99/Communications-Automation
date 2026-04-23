"""
AI token budget usage model.

Moved from services/ai_budget.py to follow the project's model/service layering:
models define schema, services contain business logic.
"""
from datetime import date

from sqlalchemy import Date, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AIBudgetUsage(Base):
    """Daily token usage accumulator. One row per calendar date."""
    __tablename__ = "ai_budget_usage"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return (
            f"<AIBudgetUsage date={self.date} "
            f"input={self.input_tokens} output={self.output_tokens}>"
        )
