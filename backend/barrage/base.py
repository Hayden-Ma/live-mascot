from abc import ABC, abstractmethod
from typing import AsyncIterator

from ..schemas import BarrageMessage


class BarrageSource(ABC):
    """弹幕数据源。实现方只负责产出 BarrageMessage，不关心下游处理。"""

    @abstractmethod
    def stream(self) -> AsyncIterator[BarrageMessage]:
        raise NotImplementedError
