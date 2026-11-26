from sqlite3 import Connection

from assets.samples import AssetVersion, validate_sample
from assets.store import fetch_asset_version, insert_asset_version
from mix.errors import BroadcastError
from mix.values import require_id, require_name


def register_asset(db: Connection, name, sample) -> AssetVersion:
    return insert_asset_version(db, require_name(name, 'name'), validate_sample(sample))


def require_asset(db: Connection, version) -> AssetVersion:
    asset = fetch_asset_version(db, require_id(version, 'asset_version'))
    if asset is None:
        raise BroadcastError(404, 'unknown_asset', 'asset version does not exist')
    return asset
