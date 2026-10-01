"""The provider registry.

Adding a portal family is one module and one entry here. Nothing else - not the
manifest format, not the roster, not the routes, not the UI - has to learn
about it.

The registry is also what ``agents/verify.py`` reaches for: each module exports
a transport-free ``recognize(url)`` and ``metadata_evidence(payload)``, so the
URL knowledge for a provider lives in exactly one place instead of being
half-copied into the agent verifier.
"""

from __future__ import annotations

from utk_curio.backend.app.discovery.domain.errors import CapabilityUnsupported
from utk_curio.backend.app.discovery.domain.manifest import (
    PORTAL_PROVIDER_TYPES,
    PROVIDER_TYPES,
    STORAGE_PROVIDER_TYPES,
    DiscoverySourceManifest,
)
from utk_curio.backend.app.discovery.infrastructure.transport import DiscoveryTransport
from utk_curio.backend.app.discovery.providers import arcgis, ckan, direct, socrata, wfs
from utk_curio.backend.app.discovery.providers.base import BaseProvider, DiscoveryProvider
from utk_curio.backend.app.discovery.providers.folder import FolderStorage
from utk_curio.backend.app.discovery.providers.huggingface import HuggingFaceStorage
from utk_curio.backend.app.discovery.providers.s3 import S3Storage
from utk_curio.backend.app.discovery.providers.storage_base import StorageProvider

PROVIDERS: dict[str, type[BaseProvider]] = {
    socrata.SocrataProvider.type: socrata.SocrataProvider,
    ckan.CkanProvider.type: ckan.CkanProvider,
    arcgis.ArcgisProvider.type: arcgis.ArcgisProvider,
    wfs.WfsProvider.type: wfs.WfsProvider,
    direct.DirectProvider.type: direct.DirectProvider,
}

#: Storage providers: a folder, a bucket, a repo. Listed and read in place,
#: organized by the manifest's resources rather than searched.
STORAGE_PROVIDERS: dict[str, type] = {
    FolderStorage.type: FolderStorage,
    S3Storage.type: S3Storage,
    HuggingFaceStorage.type: HuggingFaceStorage,
}

#: The modules that can recognise a URL, in the order ``verify.py`` tries them.
#: ``direct`` is absent on purpose: it would claim every https URL and shadow
#: every other refinement, and the generic probe already handles an
#: unrecognised URL correctly.
RECOGNISERS = (socrata, arcgis, ckan, wfs)

# The manifest validator and this registry must agree, or a manifest could name
# a provider that cannot be built (or a provider could exist that no manifest
# may name). Asserted at import so the mismatch surfaces on boot rather than on
# the first search of whichever source is affected.
assert set(PROVIDERS) == set(PORTAL_PROVIDER_TYPES), (
    f"provider registry and PORTAL_PROVIDER_TYPES disagree: "
    f"{sorted(set(PROVIDERS) ^ set(PORTAL_PROVIDER_TYPES))}"
)
assert set(STORAGE_PROVIDERS) == set(STORAGE_PROVIDER_TYPES), (
    f"storage registry and STORAGE_PROVIDER_TYPES disagree: "
    f"{sorted(set(STORAGE_PROVIDERS) ^ set(STORAGE_PROVIDER_TYPES))}"
)
assert set(PROVIDERS) | set(STORAGE_PROVIDERS) == set(PROVIDER_TYPES)


def build_provider(manifest: DiscoverySourceManifest, transport: DiscoveryTransport) -> DiscoveryProvider:
    """Construct the provider a manifest names.

    *transport* is positional and required. A default would make forgetting to
    inject a fake in a test a silent real request rather than a TypeError.
    """
    cls = PROVIDERS.get(manifest.provider.type)
    if cls is None:
        raise CapabilityUnsupported(
            f"no provider implements {manifest.provider.type!r}"
        )
    return cls(manifest, transport)


def build_storage(manifest: DiscoverySourceManifest, transport: DiscoveryTransport) -> StorageProvider:
    """Construct the storage provider a manifest names."""
    cls = STORAGE_PROVIDERS.get(manifest.provider.type)
    if cls is None:
        raise CapabilityUnsupported(
            f"{manifest.name} is not a storage source"
        )
    return cls(manifest, transport)


__all__ = [
    "PROVIDERS", "STORAGE_PROVIDERS", "RECOGNISERS", "build_provider", "build_storage",
    "DiscoveryProvider", "BaseProvider", "StorageProvider",
]
