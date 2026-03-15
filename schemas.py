from pydantic import BaseModel, Field
from typing import Optional, Literal

# Чому: Ізоляція парсингу від бізнес-логіки гарантує, що система впаде ДО спроби відкрити угоду, якщо LLM згенерує некоректний тип даних.
class TradingVerdict(BaseModel):
    analysis: str = Field(description="Мікроструктурний аналіз ринку та часу")
    synthesis: str = Field(description="Синтез факторів та логічне обґрунтування")
    direction: Literal["ЛОНГ", "ШОРТ", "ПОЗА РИНКОМ"] = Field(description="Чіткий інтрадей-вердикт")
    take_profit: Optional[float] = Field(default=None, description="Математичний тейк-профіт. Обов'язково для ЛОНГ або ШОРТ")
    stop_loss: Optional[float] = Field(default=None, description="Математичний стоп-лос за екстремумом. Обов'язково для ЛОНГ або ШОРТ")