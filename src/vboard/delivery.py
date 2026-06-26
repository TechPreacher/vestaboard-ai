import json
from typing import Protocol, runtime_checkable

import httpx

from vboard import logging_setup
from vboard.config import VestaboardConfig

log = logging_setup.get_logger("vboard.delivery")

CLOUD_RW_URL = "https://rw.vestaboard.com/"


class DeliveryError(Exception):
    pass


@runtime_checkable
class VBoard(Protocol):
    def send(self, grid: list[list[int]]) -> None: ...


class CloudRW:
    def __init__(self, key: str, client: httpx.Client | None = None) -> None:
        self._key = key
        if key:
            logging_setup.register_secret(key)
        self._client = client

    def send(self, grid: list[list[int]]) -> None:
        headers = {
            "X-Vestaboard-Read-Write-Key": self._key,
            "Content-Type": "application/json",
        }
        owns = self._client is None
        client = self._client or httpx.Client(timeout=30.0)
        try:
            resp = client.post(CLOUD_RW_URL, content=json.dumps(grid), headers=headers)
            if resp.status_code // 100 != 2:
                raise DeliveryError(f"Vestaboard HTTP {resp.status_code}")
        except httpx.HTTPError as e:
            raise DeliveryError(f"delivery failed: {e}") from e
        finally:
            if owns:
                client.close()


class LocalAPI:
    def __init__(self, endpoint: str, key: str, client: httpx.Client | None = None) -> None:
        self._endpoint = endpoint
        self._key = key
        if key:
            logging_setup.register_secret(key)
        self._client = client

    def send(self, grid: list[list[int]]) -> None:
        raise NotImplementedError("local delivery deferred to a later version")


def make_delivery(cfg: VestaboardConfig, client: httpx.Client | None = None) -> VBoard:
    if cfg.backend == "local":
        return LocalAPI(cfg.local_endpoint, cfg.local_key, client)
    return CloudRW(cfg.cloud_key, client)
