"""Mounting a source's bucket (``discovery/application/bucket_mount_sources.py``),
the mount derived from its manifest (``discovery/domain/bucket_mount.py``) and
the host check both use (``common/egress_policy.public_addresses``).

The mount service is a fake rc client that answers as rclone does: its
``mount/listmounts`` names each mount by rclone's canonical form, which CI's
``bucket-mounts`` job checks against the real service
(``scripts/bucket-mounts/ci_check.py source-mount``). How a folder looks from
Curio's container is a fake too, driven by that service. No socket opens but
the proxy test's, on loopback.
"""

from __future__ import annotations

import errno
import os
import socket
import threading
import time
from pathlib import Path
from urllib.parse import quote, urlsplit

import pytest

from utk_curio.backend.app.common import egress_policy
from utk_curio.backend.app.discovery.application import bucket_mount_check
from utk_curio.backend.app.discovery.application import bucket_mount_sources as sources_module
from utk_curio.backend.app.discovery.application.bucket_mount_sources import (
    REASONS,
    BucketMountSources,
    MountFolders,
    SourceMount,
    fs_of,
    listed_fs_of,
)
from utk_curio.backend.app.discovery.domain.bucket_mount import NotMountable, bucket_mount
from utk_curio.backend.app.discovery.domain.manifest import (
    AuthSpec,
    CapabilitySpec,
    DiscoverySourceManifest,
    ProviderSpec,
    load_source_manifest_from_dir,
)
from utk_curio.backend.app.discovery.infrastructure import bucket_mounts as bm
from utk_curio.backend.app.discovery.infrastructure.mount_proxy import MountProxy
from utk_curio.backend.app.discovery.providers.s3 import S3Storage
from utk_curio.backend.tests.test_discovery.conftest import SHIPPED_ROOT

SENTINEL = "source.aws.sentinel-2-chicago@1"
HF = "source.huggingface.documentation-images@1"

#: The fake DNS of these tests: a public address for each bucket host.
DNS = {
    "data.example.org": ["93.184.216.34"],
    "other.example.org": ["93.184.216.35"],
    "sentinel-cogs.s3.us-west-2.amazonaws.com": ["52.92.180.128", "2600:1fa0:4000::1"],
}


def resolver(host):
    try:
        return DNS[host]
    except KeyError:
        raise socket.gaierror(socket.EAI_NONAME, "Name or service not known") from None


def a_manifest(base_url, prefix="", *, kind="s3", source_id="source.example.bucket", options=None):
    """A source's manifest, built directly, so a base URL the parser refuses
    (``http://``) can be one too."""
    found = dict(options or {})
    if kind == "s3":
        found["prefix"] = prefix
    return DiscoverySourceManifest(
        id=source_id, name="Bucket", version="1.0.0", major=1,
        provider=ProviderSpec(type=kind, base_url=base_url, options=found),
        auth=AuthSpec(), capabilities=CapabilitySpec(),
    )


def shipped(dir_name):
    return load_source_manifest_from_dir(SHIPPED_ROOT / dir_name)


def parse_connection_string(fs):
    """rclone's connection string ``:<backend>,<name>=<value>,...:<path>``
    read as rclone reads it (``fspath.Parse``): a value runs to the next ``,``
    or ``:`` unless it is in quotes, where a doubled quote is one quote."""
    assert fs.startswith(":"), fs
    at, backend = 1, ""
    while fs[at] not in ",:":
        backend += fs[at]
        at += 1
    params = {}
    while fs[at] == ",":
        name, at = "", at + 1
        while fs[at] != "=":
            name += fs[at]
            at += 1
        at += 1
        value = ""
        if fs[at] in "'\"":
            mark, at = fs[at], at + 1
            while True:
                if fs[at] == mark and fs[at + 1:at + 2] == mark:
                    value, at = value + mark, at + 2
                elif fs[at] == mark:
                    at += 1
                    break
                else:
                    value, at = value + fs[at], at + 1
        else:
            while fs[at] not in ",:":
                value, at = value + fs[at], at + 1
        params[name] = value
    assert fs[at] == ":", fs
    return backend, params, fs[at + 1:]


def rclone_url(fs, path_in_mount):
    """The URL rclone's ``s3`` backend asks for the file at *path_in_mount* in
    a mount of *fs*: the remote's root is the bucket and its folder; with
    ``force_path_style`` the bucket leads the endpoint's path, else it leads
    its host (the AWS SDK's two addressing styles); the key escaped but for
    unreserved characters and ``/``."""
    backend, params, root = parse_connection_string(fs)
    assert backend == "s3"
    bucket, _, folder = root.partition("/")
    key = f"{folder}/{path_in_mount}" if folder else path_in_mount
    endpoint = urlsplit(params["endpoint"])
    if params["force_path_style"] == "true":
        return f"{endpoint.scheme}://{endpoint.netloc}/{bucket}/{quote(key, safe='/')}"
    return f"{endpoint.scheme}://{bucket}.{endpoint.netloc}/{quote(key, safe='/')}"


# ── The mount, from the manifest as it is ───────────────────────────────────


class TestTheDerivation:
    def test_a_bucket_in_the_path_is_path_style(self):
        mount = bucket_mount(a_manifest("https://data.example.org/sideseeing", "chicago/"))

        assert (mount.endpoint, mount.bucket, mount.folder, mount.tail, mount.path_style) == (
            "https://data.example.org", "sideseeing", "chicago", "", True,
        )
        assert (mount.host, mount.port) == ("data.example.org", 443)

    def test_a_port_stays_on_the_endpoint_and_is_the_one_admitted(self):
        mount = bucket_mount(a_manifest("https://data.example.org:9000/bucket"))

        assert (mount.endpoint, mount.bucket, mount.folder) == ("https://data.example.org:9000", "bucket", "")
        assert (mount.host, mount.port) == ("data.example.org", 9000)

    def test_the_shipped_sentinel_2_source_is_virtual_hosted(self):
        mount = bucket_mount(shipped(SENTINEL))

        assert (mount.endpoint, mount.bucket, mount.path_style) == (
            "https://s3.us-west-2.amazonaws.com", "sentinel-cogs", False,
        )
        assert (mount.folder, mount.tail) == ("sentinel-s2-l2a-cogs/16/T/DM/2024/7", "")
        # rclone connects to the base URL's own host, the one admitted.
        assert (mount.host, mount.port) == ("sentinel-cogs.s3.us-west-2.amazonaws.com", 443)

    def test_the_mount_is_named_after_the_sources_folder(self):
        assert bucket_mount(shipped(SENTINEL)).name == SENTINEL

    @pytest.mark.parametrize("prefix, folder, tail", [
        ("", "", ""),
        ("photos/", "photos", ""),
        ("walks/chicago/", "walks/chicago", ""),
        ("photos/img_", "photos", "img_"),
        ("img_", "", "img_"),
    ], ids=["no-prefix", "one-folder", "two-folders", "folder-and-tail", "tail-alone"])
    def test_the_prefixs_folders_are_the_mounts_folder_and_its_last_part_the_tail(self, prefix, folder, tail):
        mount = bucket_mount(a_manifest("https://data.example.org/bucket", prefix))

        assert (mount.folder, mount.tail) == (folder, tail)
        assert mount.path_of("a.jpg") == tail + "a.jpg"
        assert mount.key_of("a.jpg") == prefix + "a.jpg"

    @pytest.mark.parametrize("manifest, why", [
        (a_manifest("http://data.example.org/bucket"), "not https"),
        (a_manifest("https://data.example.org/bucket/deeper"), "not one bucket"),
        (a_manifest("https://data.example.org:99999/bucket"), "not a URL"),
        (a_manifest("https://data.example.org/bucket?list-type=2"), "more than a host and a bucket"),
        (a_manifest("https://user@data.example.org/bucket"), "more than a host and a bucket"),
        (a_manifest("https://93.184.216.34"), "no bucket in its path"),
        (a_manifest("https://bucket.localhost"), "names no bucket"),
        (a_manifest("https://data.example.org/Not_A_Bucket"), "not a bucket's name"),
        (a_manifest("https://data.example.org/bucket", "a//b/"), "empty, . or .. folder"),
        (a_manifest("https://data.example.org/bucket", "a/./"), "empty, . or .. folder"),
        (a_manifest("https://data.example.org", kind="ckan"), "is not a bucket"),
    ], ids=[
        "http", "deeper-path", "bad-port", "query", "userinfo", "address-with-no-path",
        "single-label-endpoint", "bad-bucket-name", "empty-folder", "dot-folder", "not-a-bucket",
    ])
    def test_anything_else_is_not_mountable_and_says_why(self, manifest, why):
        with pytest.raises(NotMountable) as refused:
            bucket_mount(manifest)
        assert why in str(refused.value)

    def test_a_hugging_face_repository_is_not_mountable(self):
        with pytest.raises(NotMountable) as refused:
            bucket_mount(shipped(HF))
        assert "Hugging Face" in str(refused.value)


class TestTheUrlsRcloneAsks:
    """rclone asks for each file at the very URL ``S3Storage`` reads it from."""

    CASES = {
        "path-style": a_manifest("https://data.example.org/sideseeing", "chicago/"),
        "path-style-with-a-port": a_manifest("https://data.example.org:9000/bucket"),
        "virtual-hosted": shipped(SENTINEL),
        "prefix-with-a-tail": a_manifest("https://data.example.org/bucket", "photos/img_"),
        "tail-alone": a_manifest("https://data.example.org/bucket", "img_"),
    }

    @pytest.mark.parametrize("case", sorted(CASES))
    @pytest.mark.parametrize("relpath", ["a.jpg", "2024/7/1/B04.tif", "walk 1/vídeo #2.mp4"],
                             ids=["flat", "nested", "spaces-and-accents"])
    def test_the_mounts_url_of_each_file_is_s3storages(self, case, relpath):
        manifest = self.CASES[case]
        mount = bucket_mount(manifest)

        assert rclone_url(fs_of(mount), mount.path_of(relpath)) == S3Storage(manifest, None).file_url(relpath)


class TestTheRemote:
    def test_the_sentinel_2_remote_as_rclone_takes_it(self):
        mount = bucket_mount(shipped(SENTINEL))

        assert fs_of(mount) == (
            ":s3,provider=Other,endpoint='https://s3.us-west-2.amazonaws.com',env_auth=false,"
            "no_head_object=true,force_path_style=false,list_version=2:"
            "sentinel-cogs/sentinel-s2-l2a-cogs/16/T/DM/2024/7"
        )
        # rclone's canonical name of it, which mount/listmounts gives; CI's
        # bucket-mounts job checks the rule against rclone itself.
        assert listed_fs_of(mount) == ":s3{W6Ns4}:sentinel-cogs/sentinel-s2-l2a-cogs/16/T/DM/2024/7"

    def test_a_value_with_a_quote_or_a_colon_is_quoted_as_rclone_reads_it(self):
        fs = bm.connection_string("s3", {"endpoint": "https://h:9000", "note": "it's,odd"}, "bucket/a b")

        assert fs == ":s3,endpoint='https://h:9000',note='it''s,odd':bucket/a b"
        assert parse_connection_string(fs) == (
            "s3", {"endpoint": "https://h:9000", "note": "it's,odd"}, "bucket/a b",
        )

    def test_the_canonical_name_is_the_same_for_any_order_of_the_parameters(self):
        one = bm.listed_fs("s3", {"provider": "Other", "endpoint": "https://h"}, "/b/f/")
        other = bm.listed_fs("s3", {"endpoint": "https://h", "provider": "Other"}, "b/f")

        assert one == other
        assert one.endswith("}:b/f")


# ── The host check ──────────────────────────────────────────────────────────


NOT_PUBLIC = {
    "private": ["10.0.0.5"],
    "loopback": ["127.0.0.1"],
    "carrier-grade-nat": ["100.64.0.1"],
    "cloud-metadata": ["169.254.169.254"],
    "ipv4-mapped-metadata": ["::ffff:169.254.169.254"],
    "ipv6-loopback": ["::1"],
    "one-public-one-private": ["93.184.216.34", "192.168.1.10"],
}


class TestTheHostCheck:
    def test_every_address_of_a_public_host_comes_back(self):
        assert egress_policy.public_addresses("sentinel-cogs.s3.us-west-2.amazonaws.com", resolver=resolver) == [
            "52.92.180.128", "2600:1fa0:4000::1",
        ]

    @pytest.mark.parametrize("kind", sorted(NOT_PUBLIC))
    def test_a_host_with_an_address_that_is_not_public_is_refused_as_check_url_refuses_it(self, kind):
        answer = NOT_PUBLIC[kind]

        with pytest.raises(egress_policy.EgressRefused) as refused:
            egress_policy.public_addresses("data.example.org", resolver=lambda host: answer)
        assert "resolves to a non-public address" in str(refused.value)
        # One check: check_url gives the very same reason.
        assert egress_policy.check_url("https://data.example.org/x", resolver=lambda host: answer) == (
            False, str(refused.value),
        )

    def test_a_host_that_does_not_resolve_is_refused(self):
        with pytest.raises(egress_policy.EgressRefused) as refused:
            egress_policy.public_addresses("nowhere.example.org", resolver=resolver)
        assert str(refused.value).startswith("the host does not resolve")
        with pytest.raises(egress_policy.EgressRefused):
            egress_policy.public_addresses("data.example.org", resolver=lambda host: [])


# ── A fake service and a fake view of its folders ───────────────────────────


def canonical(fs):
    """What rclone's ``mount/listmounts`` names a remote by: its canonical
    config string for a remote made on the fly, the root for a local folder."""
    if not fs.startswith(":"):
        return fs
    backend, params, path = parse_connection_string(fs)
    return bm.listed_fs(backend, params, path)


#: What rclone answers when its request cannot reach the proxy its
#: HTTPS_PROXY names, as CI's bucket-mounts job shows with nothing on the
#: proxy's port in its stand-in for Curio's container.
NO_WAY_OUT = (
    "operation error S3: ListObjectsV2, exceeded maximum number of attempts, 3, https response error "
    'StatusCode: 0, RequestID: , HostID: , request send failed, Get "https://{host}/": '
    "proxyconnect tcp: dial tcp 172.18.0.3:3128: connect: connection refused"
)


class FakeRclone:
    """The mount service as the backend calls it. *refuse* maps a method to
    rclone's error; *unreachable* makes every call find no service; *hold*,
    an event, holds ``mount/mount`` until it is set.

    ``operations/list`` lists a remote made on the fly as rclone does, out
    through its HTTPS_PROXY: a ``CONNECT`` to the remote's host on the proxy
    at *proxy_port*, on loopback. With *way_out* False its request goes
    nowhere, as when nothing the service can reach listens on the proxy's
    port; with ``"timeout"`` it is still trying when the call's deadline
    comes."""

    def __init__(self):
        self.calls = []
        self.mounts = {}
        self.dead = set()
        self.refuse = {}
        self.unreachable = False
        self.hold = None
        self.way_out = True
        self.proxy_port = None

    def call(self, method, params=None, *, timeout=None):
        params = dict(params or {})
        self.calls.append((method, params))
        if self.unreachable:
            raise bm.RcError("unreachable",
                             "nothing answers on the mount service's socket /run/x/rc.sock: No such file or directory")
        if method in self.refuse:
            raise bm.RcError("refused", f"the mount service refused {method}: {self.refuse[method]}")
        if method == "operations/list":
            raise self._listing_through_the_proxy(params["fs"], timeout)
        if method == "mount/listmounts":
            return {"mountPoints": [
                {"Fs": canonical(fs), "MountPoint": point, "MountedOn": "2026-11-07T00:00:00Z"}
                for point, fs in sorted(self.mounts.items())
            ]}
        if method == "mount/mount":
            if self.hold is not None:
                self.hold.wait(10)
            self.mounts[params["mountPoint"]] = params["fs"]
            self.dead.discard(params["mountPoint"])
        elif method == "mount/unmount":
            if params["mountPoint"] not in self.mounts:
                raise bm.RcError("refused", "the mount service refused mount/unmount: mount not found")
            del self.mounts[params["mountPoint"]]
        return {}

    def _listing_through_the_proxy(self, fs, timeout):
        """What rclone answers a listing of the remote *fs* with, out through
        the proxy: an error, since the proxy refuses every host but a
        source's, and with no proxy to reach there is no listing either."""
        host = urlsplit(parse_connection_string(fs)[1]["endpoint"]).hostname
        if self.way_out == "timeout":
            return bm.RcError("timeout", f"the mount service did not answer operations/list within {timeout or 0:g} s")
        if not self.way_out:
            return bm.RcError("refused", "the mount service refused operations/list: " + NO_WAY_OUT.format(host=host))
        with socket.create_connection(("127.0.0.1", self.proxy_port), timeout=10) as sock:
            sock.sendall(f"CONNECT {host}:443 HTTP/1.1\r\nHost: {host}:443\r\n\r\n".encode("ascii"))
            head = b""
            while b"\r\n" not in head:
                chunk = sock.recv(1024)
                if not chunk:
                    break
                head += chunk
        # Go's transport makes a refused CONNECT an error of its reason.
        reason = head.split(b"\r\n", 1)[0].decode("latin-1").partition(" ")[2].partition(" ")[2] or "no answer"
        return bm.RcError("refused", f'the mount service refused operations/list: request send failed, '
                                     f'Get "https://{host}/": {reason}')

    def methods(self):
        return [method for method, _ in self.calls]


class FakeFolders:
    """Curio's view of the service's mounts: a folder is mounted while the
    service holds its mount, dead when the service marks it so. *refuse*
    makes a folder's listing fail as a bucket that refuses listing does,
    *not_here* keeps a mount from reaching this container, and *hang*, an
    event, holds every listing until it is set."""

    def __init__(self, service):
        self.service = service
        self.refuse = set()
        self.not_here = set()
        self.hang = None
        self.looks = []
        self.lists = []

    def _held(self, folder):
        point = f"{bm.SERVICE_MOUNTS}/{folder.name}"
        return point in self.service.mounts and folder.name not in self.not_here, point

    def look(self, folder):
        self.looks.append(folder.name)
        held, point = self._held(folder)
        if not held:
            return "absent"
        return "dead" if point in self.service.dead else "mounted"

    def list(self, folder):
        self.lists.append(folder.name)
        if self.hang is not None:
            self.hang.wait(10)
        if folder.name in self.refuse:
            raise OSError(errno.EIO, os.strerror(errno.EIO))
        return self._held(folder)[0]


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch):
    """The module's service, its proxy and /monitor's line start anew."""
    from utk_curio.backend.app.monitor import errors

    monkeypatch.setenv(bm.DIR_VARIABLE, "/bucket-mounts")
    monkeypatch.setenv(bm.SOCKET_VARIABLE, "/run/curio-bucket-mounts/rc.sock")
    errors.reset()
    bucket_mount_check.reset()
    sources_module.reset()
    yield
    sources_module.reset()
    bucket_mount_check.reset()
    errors.reset()


@pytest.fixture
def rig(tmp_path):
    """A service, its folders as Curio sees them, a clock, the proxy, and the
    sources' mounts over them. The proxy listens on loopback, as ``serve()``
    starts it, and the service's requests out reach it there."""
    service = FakeRclone()
    folders = FakeFolders(service)
    clock = Clock()
    proxy = MountProxy()
    service.proxy_port = proxy.start("127.0.0.1", 0)
    mounts = BucketMountSources(service, tmp_path, proxy=proxy, folders=folders, resolver=resolver,
                                clock=clock, list_seconds=0.3)
    try:
        yield mounts, service, folders, clock, proxy
    finally:
        proxy.stop()


PATH_STYLE = a_manifest("https://data.example.org/sideseeing", "chicago/")
NAME = "source.example.bucket@1"
POINT = f"/mounts/{NAME}"


# ── Mounting a source ───────────────────────────────────────────────────────


class TestEnsure:
    def test_a_source_mounts_with_these_very_calls(self, rig, tmp_path):
        mounts, service, folders, _clock, proxy = rig

        found = mounts.ensure(PATH_STYLE)

        assert found == SourceMount("mounted", folder=tmp_path / NAME, tail="")
        assert service.calls == [
            ("mount/listmounts", {}),
            ("operations/mkdir", {"fs": "/mounts", "remote": NAME}),
            ("mount/mount", {
                "fs": ":s3,provider=Other,endpoint='https://data.example.org',env_auth=false,"
                      "no_head_object=true,force_path_style=true,list_version=2:sideseeing/chicago",
                "mountPoint": POINT, "mountType": "mount",
                "allow_other": True, "read_only": True, "vfs_cache_mode": "off",
                "file_perms": "0444", "dir_perms": "0555", "dir_cache_time": "5m",
            }),
        ]
        # The listing that proves the bucket answers, through this container.
        assert folders.lists == [NAME]
        assert proxy.admits("data.example.org", 443)

    def test_a_mounted_source_asks_nothing_again_until_it_is_looked_at(self, rig):
        mounts, service, folders, clock, _proxy = rig
        mounts.ensure(PATH_STYLE)
        calls, looks = len(service.calls), len(folders.looks)

        clock.now += 1
        assert mounts.ensure(PATH_STYLE).mounted
        assert (len(service.calls), len(folders.looks)) == (calls, looks)

        clock.now += sources_module.LOOK_SECONDS
        assert mounts.ensure(PATH_STYLE).mounted
        assert len(service.calls) == calls
        assert len(folders.looks) == looks + 1

    def test_the_tail_comes_back_for_paths_in_the_mount(self, rig):
        mounts, _service, _folders, _clock, _proxy = rig

        found = mounts.ensure(a_manifest("https://data.example.org/bucket", "photos/img_"))

        assert (found.state, found.tail) == ("mounted", "img_")

    @pytest.mark.parametrize("kind", sorted(NOT_PUBLIC))
    def test_a_host_that_is_not_public_sends_no_call_and_keeps_the_reason(self, rig, kind, monkeypatch):
        mounts, service, _folders, clock, proxy = rig
        monkeypatch.setitem(DNS, "data.example.org", NOT_PUBLIC[kind])

        found = mounts.ensure(PATH_STYLE)

        assert found.state == "down"
        assert "resolves to a non-public address" in found.reason
        assert service.calls == []
        assert not proxy.admits("data.example.org", 443)
        clock.now += 30
        assert mounts.ensure(PATH_STYLE).reason == found.reason
        assert service.calls == []

    def test_a_source_that_does_not_mount_asks_nothing(self, rig):
        mounts, service, _folders, _clock, _proxy = rig

        found = mounts.ensure(shipped(HF))

        assert found.state == "not-mountable"
        assert "Hugging Face" in found.reason
        assert service.calls == []


class TestFailures:
    def _down(self, rig, reason):
        mounts, service, _folders, _clock, proxy = rig
        found = mounts.ensure(PATH_STYLE)
        assert (found.state, found.reason) == ("down", reason)
        assert POINT not in service.mounts
        assert not proxy.admits("data.example.org", 443)
        return found

    def test_a_service_that_is_down(self, rig):
        _mounts, service, _folders, _clock, _proxy = rig
        service.unreachable = True

        self._down(rig, REASONS["service"])
        assert service.methods() == ["mount/listmounts"]

    def test_rclones_error_is_the_reason(self, rig):
        _mounts, service, _folders, _clock, _proxy = rig
        service.refuse["mount/mount"] = "failed to mount FUSE fs: mountpoint is busy"

        self._down(rig, "the mount service refused mount/mount: failed to mount FUSE fs: mountpoint is busy")

    def test_a_bucket_that_refuses_listing_is_unmounted(self, rig):
        _mounts, service, folders, _clock, _proxy = rig
        folders.refuse.add(NAME)

        self._down(rig, REASONS["listing"])
        # The service reached Curio's proxy, so the refusal is the bucket's.
        assert service.methods()[-3:] == ["mount/mount", "operations/list", "mount/unmount"]

    def test_a_mount_that_did_not_reach_this_container_is_unmounted(self, rig):
        _mounts, service, folders, _clock, _proxy = rig
        folders.not_here.add(NAME)

        self._down(rig, REASONS["not-propagated"])
        assert service.methods()[-1] == "mount/unmount"

    @pytest.mark.parametrize("listing", ["fails", "gives-no-answer"])
    def test_a_service_that_cannot_reach_curios_proxy_is_named_not_the_bucket(self, rig, listing):
        """A fresh mount's listing fails, or gives no answer, when the
        service's requests reach no proxy: a refused connection to the
        proxy's port, no route to it, or one that times out."""
        mounts, service, folders, _clock, _proxy = rig
        if listing == "fails":
            service.way_out = False
            folders.refuse.add(NAME)
        else:
            service.way_out = "timeout"
            folders.hang = threading.Event()
        try:
            found = mounts.ensure(PATH_STYLE)
        finally:
            if folders.hang is not None:
                folders.hang.set()

        assert found.state == "down"
        assert found.reason not in (REASONS["listing"], REASONS["timeout"]), (
            f"a mount whose service reaches no proxy is down for {found.reason!r}, which points at the bucket"
        )
        assert "Curio's proxy" in found.reason
        assert POINT not in service.mounts

    def test_the_proxy_named_is_the_one_on_port_3128(self, rig):
        mounts, service, folders, _clock, _proxy = rig
        service.way_out = False
        folders.refuse.add(NAME)

        assert mounts.ensure(PATH_STYLE).reason == REASONS["proxy"] == (
            "the mount service cannot reach Curio's proxy on port 3128"
        )

    def test_a_way_out_still_trying_at_its_deadline_is_not_the_service_lost(self, rig):
        mounts, service, folders, _clock, _proxy = rig
        bucket_mount_check.record(bm.SelfTest(True, None, "passed"))
        service.way_out = "timeout"
        folders.refuse.add(NAME)

        assert mounts.ensure(PATH_STYLE).reason == REASONS["proxy"]
        assert bucket_mount_check.status() == {"state": "passed", "problem": None}

    def test_with_the_proxy_in_another_process_a_failed_listing_keeps_its_reason(self, tmp_path):
        """In a start of several backend processes the home process runs the
        proxy, and this one cannot tell whether the service reaches it."""
        service = FakeRclone()
        folders = FakeFolders(service)
        folders.refuse.add(NAME)
        mounts = BucketMountSources(service, tmp_path, proxy=MountProxy(), folders=folders, resolver=resolver,
                                    list_seconds=0.3)

        assert mounts.ensure(PATH_STYLE).reason == REASONS["listing"]
        assert "operations/list" not in service.methods()

    def test_a_listing_with_no_answer_holds_one_thread_and_never_the_caller(self, rig):
        mounts, service, folders, clock, _proxy = rig
        folders.hang = threading.Event()
        try:
            started = time.monotonic()
            self._down(rig, REASONS["timeout"])
            assert time.monotonic() - started < 5
            assert service.methods()[-1] == "mount/unmount"

            clock.now += sources_module.RETRY_SECONDS
            assert mounts.ensure(PATH_STYLE).reason == REASONS["timeout"]
            # The first listing is still stuck: no second thread joins it.
            assert folders.lists == [NAME]
        finally:
            folders.hang.set()

    def test_a_failed_source_waits_a_minute_and_answers_its_reason_meanwhile(self, rig):
        mounts, service, _folders, clock, _proxy = rig
        service.unreachable = True
        first = mounts.ensure(PATH_STYLE)
        calls = len(service.calls)

        service.unreachable = False
        clock.now += sources_module.RETRY_SECONDS - 1
        assert mounts.ensure(PATH_STYLE) == first
        assert len(service.calls) == calls

        clock.now += 1
        assert mounts.ensure(PATH_STYLE).mounted
        assert "mount/mount" in service.methods()[calls:]


class TestRemounts:
    def test_a_dead_mount_is_unmounted_and_mounted_again(self, rig):
        mounts, service, _folders, clock, _proxy = rig
        mounts.ensure(PATH_STYLE)
        service.dead.add(POINT)
        calls = len(service.calls)

        clock.now += sources_module.LOOK_SECONDS
        assert mounts.ensure(PATH_STYLE).mounted
        assert service.methods()[calls:] == [
            "mount/listmounts", "mount/unmount", "operations/mkdir", "mount/mount",
        ]
        assert POINT not in service.dead

    def test_a_mount_the_service_lost_is_mounted_again(self, rig):
        mounts, service, _folders, clock, _proxy = rig
        mounts.ensure(PATH_STYLE)
        # The service restarted, and its start cleared the dead mount.
        service.mounts.clear()
        calls = len(service.calls)

        clock.now += sources_module.LOOK_SECONDS
        assert mounts.ensure(PATH_STYLE).mounted
        assert service.methods()[calls:] == ["mount/listmounts", "operations/mkdir", "mount/mount"]

    def test_a_mount_whose_manifest_names_another_folder_now_is_mounted_again(self, rig):
        mounts, service, _folders, _clock, _proxy = rig
        mounts.ensure(PATH_STYLE)
        calls = len(service.calls)

        moved = a_manifest("https://data.example.org/sideseeing", "sao-paulo/")
        assert mounts.ensure(moved).mounted
        assert service.methods()[calls:] == [
            "mount/listmounts", "mount/unmount", "operations/mkdir", "mount/mount",
        ]
        assert service.mounts[POINT].endswith(":sideseeing/sao-paulo")

    def test_a_mount_made_before_a_backend_restart_is_taken_as_it_is(self, rig, tmp_path):
        _mounts, service, folders, clock, proxy = rig
        BucketMountSources(service, tmp_path, proxy=MountProxy(), folders=folders, resolver=resolver,
                           clock=clock).ensure(PATH_STYLE)
        service.calls.clear()

        restarted = BucketMountSources(service, tmp_path, proxy=proxy, folders=folders, resolver=resolver,
                                       clock=clock)
        assert restarted.ensure(PATH_STYLE).mounted
        assert service.methods() == ["mount/listmounts"]
        assert proxy.admits("data.example.org", 443)

    def test_one_mount_of_a_source_at_a_time(self, rig):
        mounts, service, _folders, _clock, _proxy = rig
        service.hold = threading.Event()
        found = []
        callers = [threading.Thread(target=lambda: found.append(mounts.ensure(PATH_STYLE))) for _ in range(2)]
        for caller in callers:
            caller.start()
        deadline = time.monotonic() + 5
        while "mount/mount" not in service.methods() and time.monotonic() < deadline:
            time.sleep(0.01)
        time.sleep(0.1)
        service.hold.set()
        for caller in callers:
            caller.join(5)

        assert service.methods().count("mount/mount") == 1
        assert [entry.state for entry in found] == ["mounted", "mounted"]


class TestAtBackendStart:
    KEPT = a_manifest("https://data.example.org/kept", source_id="source.example.kept")
    MOVED = a_manifest("https://data.example.org/moved", "new/", source_id="source.example.moved")
    PRIVATE = a_manifest("https://other.example.org/private", source_id="source.example.private")

    def _service_with_mounts(self):
        service = FakeRclone()
        service.mounts = {
            "/mounts/.selftest": "/selftest",
            "/mounts/source.example.kept@1": fs_of(bucket_mount(self.KEPT)),
            "/mounts/source.example.removed@1": fs_of(bucket_mount(
                a_manifest("https://data.example.org/gone", source_id="source.example.removed"))),
            "/mounts/source.example.moved@1": fs_of(bucket_mount(
                a_manifest("https://data.example.org/moved", "old/", source_id="source.example.moved"))),
            "/mounts/source.example.private@1": fs_of(bucket_mount(self.PRIVATE)),
        }
        return service

    def test_mounts_of_listed_sources_are_admitted_again_and_every_other_is_unmounted(self, tmp_path, monkeypatch):
        monkeypatch.setitem(DNS, "other.example.org", ["10.1.2.3"])
        service = self._service_with_mounts()
        folders, clock, proxy = FakeFolders(service), Clock(), MountProxy()
        mounts = BucketMountSources(service, tmp_path, proxy=proxy, folders=folders, resolver=resolver, clock=clock)

        mounts.reconcile(lambda: [self.KEPT, self.MOVED, self.PRIVATE])

        assert sorted(params["mountPoint"] for method, params in service.calls if method == "mount/unmount") == [
            "/mounts/source.example.moved@1", "/mounts/source.example.private@1", "/mounts/source.example.removed@1",
        ]
        assert sorted(service.mounts) == ["/mounts/.selftest", "/mounts/source.example.kept@1"]
        assert proxy.admits("data.example.org", 443)
        assert not proxy.admits("other.example.org", 443)

        service.calls.clear()
        # The kept mount is looked at, then taken as it is.
        assert mounts.ensure(self.KEPT).mounted
        assert service.calls == []
        assert folders.looks == ["source.example.kept@1"]
        # The private host's failure is kept: it is not tried for a minute.
        down = mounts.ensure(self.PRIVATE)
        assert down.state == "down" and "non-public address" in down.reason
        assert service.calls == []

    def test_with_no_mounts_the_catalog_is_not_read(self, tmp_path):
        service, read = FakeRclone(), []
        mounts = BucketMountSources(service, tmp_path, proxy=MountProxy(), folders=FakeFolders(service),
                                    resolver=resolver)

        def catalog():
            read.append("catalog")
            return []

        mounts.reconcile(catalog)

        assert service.methods() == ["mount/listmounts"]
        assert read == []

    def test_a_service_that_is_down_at_start_is_left_for_later(self, tmp_path):
        service = self._service_with_mounts()
        service.unreachable = True
        mounts = BucketMountSources(service, tmp_path, proxy=MountProxy(), folders=FakeFolders(service),
                                    resolver=resolver)

        mounts.reconcile(lambda: [self.KEPT])

        assert service.methods() == ["mount/listmounts"]


class TestTheMonitorLine:
    def test_a_call_that_finds_the_service_gone_makes_it_unavailable_until_one_is_answered(self, rig):
        from utk_curio.backend.app.monitor import errors

        mounts, service, _folders, clock, _proxy = rig
        bucket_mount_check.record(bm.SelfTest(True, None, "passed"))
        service.unreachable = True

        mounts.ensure(PATH_STYLE)
        assert bucket_mount_check.status() == {"state": "unavailable", "problem": bm.PROBLEMS["no-service"]}
        clock.now += sources_module.RETRY_SECONDS
        mounts.ensure(PATH_STYLE)
        # One Recent error for the loss, not one per call.
        [entry] = errors.snapshot()["errors"]
        assert entry["summary"] == f"Bucket mounts are unavailable: {bm.PROBLEMS['no-service']}"
        assert "rc.sock" in entry["detail"]

        service.unreachable = False
        clock.now += sources_module.RETRY_SECONDS
        assert mounts.ensure(PATH_STYLE).mounted
        assert bucket_mount_check.status() == {"state": "passed", "problem": None}

    def test_rclones_refusal_is_an_answer(self, rig):
        mounts, service, _folders, _clock, _proxy = rig
        bucket_mount_check.record(bm.SelfTest(True, None, "passed"))
        bucket_mount_check.service_lost("no-service", "nothing answered")
        service.refuse["mount/mount"] = "mountpoint is busy"

        mounts.ensure(PATH_STYLE)

        assert bucket_mount_check.status() == {"state": "passed", "problem": None}

    def test_a_self_test_that_found_no_service_runs_again_once_the_service_answers(self, rig, monkeypatch):
        mounts, _service, _folders, _clock, _proxy = rig
        bucket_mount_check.record(bm.SelfTest(False, "no-service", "nothing answers on /run/x/rc.sock"))
        assert bucket_mount_check.status()["state"] == "unavailable"
        monkeypatch.setattr(bm, "self_test_from_env", lambda **_settings: bm.SelfTest(True, None, "passed"))
        reconciled = []
        monkeypatch.setattr(sources_module, "reconcile_at_start", lambda: reconciled.append(True))

        assert mounts.ensure(PATH_STYLE).mounted
        bucket_mount_check._thread.join(5)

        assert bucket_mount_check.status() == {"state": "passed", "problem": None}
        assert reconciled == [True]

    def test_a_self_test_that_failed_otherwise_lets_no_source_mount(self, rig):
        mounts, service, _folders, _clock, _proxy = rig
        bucket_mount_check.record(bm.SelfTest(False, "not-readable", "reading as curio-exec: Permission denied"))

        found = mounts.ensure(PATH_STYLE)

        assert (found.state, found.reason) == (
            "down", f"the mount service failed its self-test: {bm.PROBLEMS['not-readable']}",
        )
        assert service.calls == []


class TestTheProcessService:
    def test_with_no_service_named_a_source_reads_as_it_does_without_mounts(self, monkeypatch):
        monkeypatch.delenv(bm.SOCKET_VARIABLE)

        assert sources_module.ensure(PATH_STYLE) == SourceMount("none")
        assert sources_module.start_proxy("127.0.0.1") is False

    def test_the_proxy_starts_on_the_backends_host(self, monkeypatch):
        monkeypatch.setattr(bm, "PROXY_PORT", 0)

        assert sources_module.start_proxy("127.0.0.1") is True
        assert sources_module.sources().proxy.listening

    def test_a_proxy_that_cannot_listen_is_one_of_the_recent_errors(self, monkeypatch):
        from utk_curio.backend.app.monitor import errors

        taken = socket.create_server(("127.0.0.1", 0))
        try:
            monkeypatch.setattr(bm, "PROXY_PORT", taken.getsockname()[1])
            assert sources_module.start_proxy("127.0.0.1") is False
        finally:
            taken.close()
        [entry] = errors.snapshot()["errors"]
        assert "proxy did not start" in entry["summary"]

    def test_the_sources_follow_the_flags(self, monkeypatch):
        first = sources_module.sources()
        assert sources_module.sources() is first
        assert first.where == (Path("/bucket-mounts"), "/run/curio-bucket-mounts/rc.sock")

        monkeypatch.setenv(bm.DIR_VARIABLE, "/srv/other")
        assert sources_module.sources().where[0] == Path("/srv/other")


# ── A start of several backend processes ────────────────────────────────────


class ListedThroughTheProxy(FakeFolders):
    """Curio's view of the service's mounts, each listing going out through
    the proxy at *proxy_port*, on loopback, as rclone's does: a ``CONNECT`` to
    the host and port rclone asks the bucket at, and a listing that fails as
    FUSE fails it (``EIO``) unless the proxy opens the tunnel. :attr:`answers`
    keeps the status line of each answer."""

    def __init__(self, service, proxy_port):
        super().__init__(service)
        self.proxy_port = proxy_port
        self.answers = []

    def list(self, folder):
        fs = self.service.mounts.get(f"{bm.SERVICE_MOUNTS}/{folder.name}")
        if fs is not None:
            asked = urlsplit(rclone_url(fs, ""))
            status = self._connect(asked.hostname, asked.port or 443)
            self.answers.append(status)
            if not status.startswith("HTTP/1.1 200 "):
                raise OSError(errno.EIO, os.strerror(errno.EIO))
        return super().list(folder)

    def _connect(self, host, port):
        """The status line the proxy answers a ``CONNECT`` to *host* at *port* with."""
        with socket.create_connection(("127.0.0.1", self.proxy_port), timeout=10) as sock:
            sock.sendall(f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n\r\n".encode("ascii"))
            head = b""
            while b"\r\n" not in head:
                chunk = sock.recv(1024)
                if not chunk:
                    break
                head += chunk
        return head.split(b"\r\n", 1)[0].decode("latin-1") or "no answer"


class TestAStartOfSeveralProcesses:
    """``curio.py start --backend-processes N``. The home process, this test's,
    runs the one proxy that listens, as ``serve()`` starts it
    (``start_proxy``). Each other process of the start is a forked child
    (``_support/two_processes.py``), which mounts a source as the owner of a
    dataflow does for a node's collection or a media read, its listing going
    out through home's proxy as the mount service's requests do."""

    HOST = "data.example.org"

    @pytest.fixture
    def start(self, tmp_path, monkeypatch):
        """A start of the given number of processes with a state folder of its
        own: home's proxy listening on loopback, the bucket's host a server on
        loopback that takes connections, and a source at that host and port.
        Gives home's proxy, the port it listens on, the source and the port of
        the source's host."""
        upstream = socket.create_server(("127.0.0.1", 0))
        port = upstream.getsockname()[1]
        monkeypatch.setenv("CURIO_STATE_DIR", str(tmp_path / "state"))
        monkeypatch.setattr(bm, "PROXY_PORT", 0)
        # The bucket's host is the server on loopback, which these tests take
        # as public, as test_mount_proxy.py's tunnels do; any other host is
        # Curio's policy's to judge.
        policy = egress_policy.public_addresses

        def the_bucket_is_public(host, *, resolver=None):
            return ["127.0.0.1"] if host == self.HOST else policy(host, resolver=resolver)

        monkeypatch.setattr(egress_policy, "public_addresses", the_bucket_is_public)

        def begin(processes):
            monkeypatch.setenv("CURIO_BACKEND_PROCESSES", str(processes))
            monkeypatch.setenv("CURIO_BACKEND_PROCESS", "0")
            assert sources_module.start_proxy("127.0.0.1")
            home = sources_module.process_proxy()
            source = a_manifest(f"https://{self.HOST}:{port}/sideseeing", "chicago/")
            return home, home.start("127.0.0.1", 0), source, port

        try:
            yield begin
        finally:
            upstream.close()

    @staticmethod
    def _in_process(number, work):
        """*work* in the start's process *number*, a forked child that holds no
        proxy and no mount of its own yet, as a process of its own starts:
        what it raised, or ""."""
        from utk_curio.backend.tests._support.two_processes import in_another_process

        def run():
            os.environ["CURIO_BACKEND_PROCESS"] = str(number)
            # The module's proxy and sources here are copies of home's, the
            # test process's; a process of its own makes its own.
            sources_module._proxy = sources_module._sources = None
            work()

        return in_another_process(run)

    @staticmethod
    def _mounts(service, folders, root):
        """The sources' mounts of this process over *service*, with its proxy."""
        return BucketMountSources(service, root, proxy=sources_module.process_proxy(), folders=folders,
                                  resolver=resolver)

    def test_a_source_another_process_mounts_gets_its_host_through_homes_proxy(self, start, tmp_path):
        """Process 1 owns the dataflow whose node reads a source's collection,
        or whose page reads its media, so it mounts the source. Its listing,
        and every read after it, goes out through home's proxy, which must
        let the source's host through. Each process kept the hosts it let
        through in its own memory, read by no proxy but its own, which never
        listens: home's refused the CONNECT, and the mount was down for "the
        bucket refuses listing"."""
        home, proxy_port, source, port = start(2)

        def mounts_the_source():
            service = FakeRclone()
            folders = ListedThroughTheProxy(service, proxy_port)
            found = self._mounts(service, folders, tmp_path).ensure(source)
            assert found.mounted, (
                f"process 1's mount of the source is {found.state}, for {found.reason!r}: "
                f"home's proxy answered its listing {folders.answers}"
            )

        error = self._in_process(1, mounts_the_source)
        assert error == "", error
        assert home.admits(self.HOST, port), (
            "home's proxy, which the mount service reaches, does not let through the host of a source "
            "process 1 mounted"
        )

    def test_a_mount_that_fails_in_one_process_leaves_the_host_to_the_process_that_holds_one(
            self, start, tmp_path):
        """Process 1 holds a mount of the source. Process 2's look at it fails
        (its listing is refused), so process 2 lets the host go: home's proxy
        still lets it through for process 1, until process 1 lets it go too."""
        home, proxy_port, source, port = start(3)

        def mounts_the_source():
            service = FakeRclone()
            folders = ListedThroughTheProxy(service, proxy_port)
            found = self._mounts(service, folders, tmp_path).ensure(source)
            assert found.mounted, (
                f"process 1's mount of the source is {found.state}, for {found.reason!r}: "
                f"home's proxy answered its listing {folders.answers}"
            )

        def fails_to_list_it():
            service = FakeRclone()
            # The service holds process 1's mount of the source.
            service.mounts[POINT] = fs_of(bucket_mount(source))
            folders = ListedThroughTheProxy(service, proxy_port)
            folders.refuse.add(NAME)
            found = self._mounts(service, folders, tmp_path).ensure(source)
            assert (found.state, found.reason) == ("down", REASONS["listing"]), found
            assert POINT in service.mounts, "process 2 unmounted a mount it did not make"

        def lets_it_go():
            sources_module.process_proxy().withdraw(NAME)

        error = self._in_process(1, mounts_the_source)
        assert error == "", error
        error = self._in_process(2, fails_to_list_it)
        assert error == "", error
        assert home.admits(self.HOST, port), (
            "process 2's failed look at the source took the host from process 1, which still holds its mount"
        )
        error = self._in_process(1, lets_it_go)
        assert error == "", error
        assert not home.admits(self.HOST, port), "home's proxy lets a host through that no process holds"

    def test_a_start_of_one_process_keeps_the_hosts_it_lets_through_in_its_memory(self, tmp_path, monkeypatch):
        from utk_curio.backend.app.common import shared_budgets, user_storage

        monkeypatch.setenv("CURIO_STATE_DIR", str(tmp_path / "state"))
        monkeypatch.delenv("CURIO_BACKEND_PROCESSES", raising=False)
        monkeypatch.delenv("CURIO_BACKEND_PROCESS", raising=False)
        service = FakeRclone()

        assert self._mounts(service, FakeFolders(service), tmp_path).ensure(PATH_STYLE).mounted
        assert sources_module.process_proxy().admits("data.example.org", 443)
        folder = user_storage.curio_root() / shared_budgets.FOLDER
        assert not folder.exists(), sorted(str(path) for path in folder.rglob("*"))

    def test_each_start_begins_with_no_host_let_through(self, start, monkeypatch):
        """The hosts one start let through are its own: the next start's
        proxy lets none of them through, as a process's memory starts empty."""
        from utk_curio.backend.app.common import shared_budgets

        home, _proxy_port, _source, port = start(2)
        home.admit(NAME, self.HOST, port)
        assert home.admits(self.HOST, port)

        monkeypatch.setattr(shared_budgets, "BOOT_ID", "the next start")
        sources_module.reset()

        assert not sources_module.process_proxy().admits(self.HOST, port), (
            "the next start's proxy lets through a host the start before it let through"
        )


class TestTheFolders:
    """The operating system's view, on folders that are no mount."""

    def test_a_missing_folder_is_absent_and_a_plain_one_is_no_mount(self, tmp_path):
        folders = MountFolders()

        assert folders.look(tmp_path / "missing") == "absent"
        assert folders.look(tmp_path) == "absent"
        assert folders.list(tmp_path) is False
        with pytest.raises(OSError):
            folders.list(tmp_path / "missing")

    def test_a_mount_point_is_mounted(self):
        assert MountFolders().look(Path(os.path.abspath(os.sep))) == "mounted"
