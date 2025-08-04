from typing import List, Optional

from pydantic import BaseModel


class FundingRateConfig(BaseModel):
    """
    The FundingRateConfig class is a data class that stores the configuration of a FundingRate object.
    It has the following attributes:
    - connector: str
    - trading_pair: str
    """
    connector: str
    trading_pairs: Optional[List[str]]
    rest_api_update_interval: float
    standardization_duration_hours: int


# class HistoricalFundingRateConfig(BaseModel):
#     connector_name: str
#     trading_pair: str
#     start_time: int
#     end_time: int
