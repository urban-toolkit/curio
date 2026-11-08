"""Where a Discovery source's bucket mounts, from its manifest as it is.

A source's bucket mounts on a deployment that runs the bucket mount service
(``infrastructure/bucket_mounts.py``) when its provider is ``s3`` and its
``https://`` base URL names the bucket one of two ways:

- ``https://host[:port]/<bucket>``, one path segment: path-style, at the
  endpoint ``https://host[:port]``;
- ``https://<bucket>.<host>``, no path: virtual-hosted, at the endpoint
  ``https://<host>``, the bucket the host's first label (the shipped
  Sentinel-2 source, ``discovery/source.aws.sentinel-2-chicago@1``).

``options.prefix`` up to its last ``/`` is the folder of the bucket the mount
shows. A prefix that does not end in ``/`` leaves its last part, the tail,
which every file's path in the mount starts with: the file
``S3Storage.file_url`` reads at ``<baseUrl>/<prefix><relpath>`` is
``<mount>/<tail><relpath>``, and rclone asks for it at that very URL.

Anything else is not mountable, with the reason, and keeps Cache files: a
Hugging Face repository (rclone has no backend for one), an ``http://``
bucket (the proxy carries HTTPS tunnels alone), a deeper path, or a URL with
more in it than a host and a bucket.

A mount is named after its source's folder, ``<sourceId>@<major>``, so the
paths node outputs save into it stay good across restarts.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from utk_curio.backend.app.discovery.domain.manifest import DiscoverySourceManifest
from utk_curio.backend.app.discovery.domain.source_id import SOURCE_DIR_RE

#: A bucket's name as S3 allows one: 3 to 63 lowercase letters, digits, dots
#: and dashes, starting and ending with a letter or digit.
_BUCKET_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
#: One label of a host name.
_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
#: Characters a prefix may not hold: control characters.
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

HTTPS_PORT = 443


class NotMountable(ValueError):
    """A source whose bucket does not mount; the message says why."""


@dataclass(frozen=True)
class BucketMount:
    """Where a source's bucket mounts.

    ``name`` is the mount's folder, the source's ``<sourceId>@<major>``;
    ``endpoint`` the S3 endpoint rclone is given; ``bucket`` and ``folder``
    the remote's root; ``tail`` what every file's path in the mount starts
    with; ``path_style`` whether the bucket goes in the URL's path rather
    than its host; ``host`` and ``port`` where rclone connects, the base
    URL's, which the proxy admits.
    """

    name: str
    endpoint: str
    bucket: str
    folder: str
    tail: str
    path_style: bool
    host: str
    port: int

    def path_of(self, relpath: str) -> str:
        """Where the source's file *relpath* is, inside the mount."""
        return self.tail + relpath

    def key_of(self, relpath: str) -> str:
        """The key of the source's file *relpath* in the bucket."""
        return (f"{self.folder}/" if self.folder else "") + self.tail + relpath


def bucket_mount(manifest: DiscoverySourceManifest) -> BucketMount:
    """Where *manifest*'s bucket mounts. Raises :class:`NotMountable`."""
    provider = manifest.provider
    if provider.type == "huggingface":
        raise NotMountable("rclone has no backend for a Hugging Face repository")
    if provider.type != "s3":
        raise NotMountable(f"its provider ({provider.type}) is not a bucket")
    name = manifest.dir_name
    if not SOURCE_DIR_RE.match(name):
        raise NotMountable(f"{name!r} is not a source's folder name")
    try:
        parts = urlsplit(provider.base_url)
        explicit_port = parts.port
    except ValueError:
        raise NotMountable("its baseUrl is not a URL") from None
    if parts.scheme != "https":
        raise NotMountable("its baseUrl is not https, and the mounts' proxy carries HTTPS alone")
    if "@" in parts.netloc or parts.query or parts.fragment:
        raise NotMountable("its baseUrl holds more than a host and a bucket")
    host = (parts.hostname or "").lower()
    if not host:
        raise NotMountable("its baseUrl names no host")
    port_part = f":{explicit_port}" if explicit_port is not None else ""
    if parts.path == "":
        endpoint_host, bucket = _virtual_hosted(host)
        endpoint, path_style = f"https://{endpoint_host}{port_part}", False
    elif re.fullmatch(r"/[^/]+", parts.path):
        bucket = parts.path[1:]
        if not _BUCKET_RE.match(bucket):
            raise NotMountable(f"its baseUrl's path, {bucket!r}, is not a bucket's name")
        netloc_host = f"[{host}]" if ":" in host else host
        endpoint, path_style = f"https://{netloc_host}{port_part}", True
    else:
        raise NotMountable("its baseUrl's path is not one bucket's name")
    # As S3Storage reads it.
    folder, tail = _prefix_parts(provider.options.get("prefix") or "")
    return BucketMount(
        name=name, endpoint=endpoint, bucket=bucket, folder=folder, tail=tail,
        path_style=path_style, host=host,
        port=explicit_port if explicit_port is not None else HTTPS_PORT,
    )


def _virtual_hosted(host: str) -> tuple[str, str]:
    """The endpoint's host and the bucket of ``https://<bucket>.<host>``."""
    if _is_address(host):
        raise NotMountable("its baseUrl is an address with no bucket in its path")
    bucket, _, endpoint_host = host.partition(".")
    if "." not in endpoint_host or not all(_LABEL_RE.match(label) for label in endpoint_host.split(".")):
        raise NotMountable("its baseUrl names no bucket: no path, and no bucket.host")
    if not (_LABEL_RE.match(bucket) and _BUCKET_RE.match(bucket)):
        raise NotMountable(f"its host's first label, {bucket!r}, is not a bucket's name")
    return endpoint_host, bucket


def _is_address(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _prefix_parts(prefix) -> tuple[str, str]:
    """``options.prefix`` as the mount's folder and the tail of every path."""
    if not isinstance(prefix, str):
        raise NotMountable("its prefix is not text")
    if prefix.startswith("/") or _CONTROL_RE.search(prefix):
        raise NotMountable("its prefix is not a relative key prefix")
    folder, _, tail = prefix.rpartition("/")
    if folder and any(part in ("", ".", "..") for part in folder.split("/")):
        raise NotMountable("its prefix has an empty, . or .. folder, which a mount cannot show")
    if tail in (".", ".."):
        raise NotMountable("its prefix ends in . or ..")
    return folder, tail
