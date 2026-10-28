"""Banco Central do Brasil — PTAX (official USD/BRL reference rate), via the Olinda OData API.

https://dadosabertos.bcb.gov.br/dataset/dolar-americano-usd-todos-os-boletins-diarios
Public, no key. One closing observation per business day (~13h Brasília).
"""

import json
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx

from app.core.logging import get_logger
from app.modules.market_data.providers.base import FxQuote, ProviderError

logger = get_logger(__name__)

SOURCE = "bcb_ptax"
_BASE_URL = "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata"
_BRASILIA = ZoneInfo("America/Sao_Paulo")


class BcbPtaxProvider:
    name = SOURCE

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(
            base_url=_BASE_URL, timeout=httpx.Timeout(20.0, connect=5.0)
        )
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def fetch_usd_brl(self, start: date, end: date) -> list[FxQuote]:
        path = "/CotacaoDolarPeriodo(dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)"
        params = {
            "@dataInicial": f"'{start:%m-%d-%Y}'",
            "@dataFinalCotacao": f"'{end:%m-%d-%Y}'",
            "$format": "json",
            "$select": "cotacaoVenda,dataHoraCotacao",
        }
        try:
            response = await self._client.get(path, params=params)
        except httpx.TransportError as exc:
            raise ProviderError("BCB PTAX unreachable") from exc
        if response.status_code != 200:
            raise ProviderError(f"BCB PTAX responded {response.status_code}")
        try:
            rows = json.loads(response.text, parse_float=Decimal)["value"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ProviderError("BCB PTAX returned an unexpected payload") from exc

        quotes: list[FxQuote] = []
        for row in rows:
            try:
                rate = Decimal(row["cotacaoVenda"])
                stamp = datetime.fromisoformat(row["dataHoraCotacao"]).replace(tzinfo=_BRASILIA)
            except (KeyError, TypeError, ValueError, ArithmeticError):
                continue
            # Sanity band: reject obviously corrupt observations instead of storing them.
            if not Decimal("0.5") < rate < Decimal("50"):
                logger.warning("ptax_rate_rejected", rate=str(rate))
                continue
            quotes.append(FxQuote("USD", "BRL", rate, stamp))
        return quotes
