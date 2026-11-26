from dataclasses import dataclass
from sqlite3 import Connection

from assets.catalog import require_asset


@dataclass(frozen=True)
class AssetPreview:
    version: int
    name: str
    sample: int


def preview_asset(db: Connection, version) -> AssetPreview:
    asset = require_asset(db, version)
    return AssetPreview(asset.version, asset.name, asset.sample)
