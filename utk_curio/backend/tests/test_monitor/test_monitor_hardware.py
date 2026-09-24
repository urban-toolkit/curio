"""The hardware section: present, typed, degrading, and naming no machine.

The degradation tests matter more than the happy path. psutil reports
different things on different kernels and raises for counters a platform does
not implement (there is no load average on Windows, no cpu_freq in many
containers), so every field has to be able to be null without taking the page
down.
"""

import builtins

import pytest

from utk_curio.backend.app.monitor import hardware


class TestPayload:
    def test_the_section_is_present_and_shaped(self, client):
        hw = client.get("/api/monitor").get_json()["hardware"]

        assert set(hw) == {"cpu", "memory", "load", "processes"}
        assert isinstance(hw["cpu"]["model"], str) and hw["cpu"]["model"]
        assert isinstance(hw["cpu"]["arch"], str) and hw["cpu"]["arch"]
        assert isinstance(hw["cpu"]["logicalCores"], int)
        assert isinstance(hw["memory"]["totalBytes"], int)
        assert hw["memory"]["totalBytes"] > 0
        assert isinstance(hw["processes"]["backendRssBytes"], int)

    def test_load_is_reported_per_core_as_well_as_raw(self):
        load = hardware._load()
        if load["avg1m"] is None:
            pytest.skip("no load average on this platform")
        cores = __import__("os").cpu_count() or 1
        assert load["perCore"] == pytest.approx(load["avg1m"] / cores, abs=0.01)

    def test_the_sandbox_rss_is_proxied_when_reachable(self, client, monkeypatch):
        from utk_curio.backend.app.monitor import routes

        monkeypatch.setattr(routes, "_sandbox_monitor",
                            lambda: {"rss_bytes": 123456789})
        hw = client.get("/api/monitor").get_json()["hardware"]
        assert hw["processes"]["sandboxRssBytes"] == 123456789

    def test_the_sandbox_rss_is_null_when_unreachable(self, client):
        hw = client.get("/api/monitor").get_json()["hardware"]
        assert hw["processes"]["sandboxRssBytes"] is None


class TestPrivacy:
    def test_the_hostname_is_not_reported(self, client):
        """Hostnames routinely encode a person, a team or an internal network.

        They also tell an operator nothing they do not already know, so the
        section omits it on purpose. This is the test that keeps it omitted.
        """
        import socket

        hostname = socket.gethostname()
        raw = client.get("/api/monitor").get_data(as_text=True)
        # Guard against a trivially-contained hostname like "a" making this
        # assertion vacuous.
        if len(hostname) >= 4:
            assert hostname not in raw
        assert "hostname" not in raw.lower()

    def test_no_network_address_is_reported(self, client):
        import re

        raw = client.get("/api/monitor").get_data(as_text=True)
        assert re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", raw) is None
        assert re.search(r"\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b", raw, re.I) is None


class TestDegradation:
    def test_every_field_is_null_rather_than_missing_without_psutil(self,
                                                                   monkeypatch):
        monkeypatch.setattr(hardware, "psutil", None)
        snap = hardware.snapshot()

        assert snap["memory"]["totalBytes"] is None
        assert snap["processes"]["backendRssBytes"] is None
        # The parts that do not need psutil still work.
        assert snap["cpu"]["model"]
        assert snap["cpu"]["logicalCores"] is not None

    def test_a_raising_psutil_does_not_break_the_snapshot(self, monkeypatch):
        class Exploding:
            def __getattr__(self, name):
                raise RuntimeError("psutil is having a bad day")

        monkeypatch.setattr(hardware, "psutil", Exploding())
        snap = hardware.snapshot()
        assert snap["memory"]["totalBytes"] is None
        assert snap["cpu"]["usagePercent"] is None

    def test_a_platform_without_load_average_reports_nulls(self, monkeypatch):
        # Windows has no getloadavg at all.
        monkeypatch.delattr(hardware.os, "getloadavg", raising=False)
        load = hardware._load()
        assert load == {"avg1m": None, "avg5m": None, "avg15m": None,
                        "perCore": None}

    def test_an_unreadable_cpuinfo_falls_back_rather_than_raising(self,
                                                                 monkeypatch):
        monkeypatch.setattr(hardware.platform, "system", lambda: "Linux")
        original_open = builtins.open

        def boom(path, *args, **kwargs):
            if str(path) == "/proc/cpuinfo":
                raise OSError("nope")
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", boom)
        assert hardware._cpu_model()  # non-empty fallback

    def test_the_route_survives_a_broken_hardware_module(self, client,
                                                         monkeypatch):
        """A monitor must never fail over the section that describes the host."""
        monkeypatch.setattr(hardware, "_memory",
                            lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        response = client.get("/api/monitor")
        assert response.status_code == 200
