from pydantic import BaseModel, Field
from typing import Optional, Literal

# Чому: Ізоляція контракту даних. Видалено default=None для сумісності з парсерами генеративних моделей, залишено лише сувору типізацію.
class TradingVerdict(BaseModel):
    analysis: str = Field(description="Мікроструктурний аналіз ринку та часу")
    synthesis: str = Field(description="Синтез факторів та логічне обґрунтування")
    direction: Literal["ЛОНГ", "ШОРТ", "ПОЗА РИНКОМ"] = Field(description="Чіткий інтрадей-вердикт")
    take_profit: Optional[float] = Field(description="Математичний тейк-профіт. Значення null, якщо ПОЗА РИНКОМ")
    stop_loss: Optional[float] = Field(description="Математичний стоп-лос за екстремумом. Значення null, якщо ПОЗА РИНКОМ")