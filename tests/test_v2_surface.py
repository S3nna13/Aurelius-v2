"""Integration smoke tests for the Aurelius v2 surface area."""

from __future__ import annotations

import asyncio
import sys

import aurelius_cli.v2_cli as cli
from src.api.server import api_hardware_detect, api_health, app
from src.runtime.hardware_detector import HardwareDetector


def test_hardware_detector_exposes_gpu_facades() -> None:
    info = HardwareDetector.detect()
    assert hasattr(info, "gpu_name")
    assert hasattr(info, "gpu_vram_gb")
    assert isinstance(info.gpu_name, str)
    assert isinstance(info.gpu_vram_gb, float)
    assert info.gpu_vram_gb >= 0.0


def test_cli_help_and_status(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["aurelius"])
    assert cli.main_v2() == 1
    help_out = capsys.readouterr().out
    assert "Usage: python -m aurelius_cli.v2_cli" in help_out

    monkeypatch.setattr(sys, "argv", ["aurelius", "status"])
    assert cli.main_v2() == 0
    status_out = capsys.readouterr().out
    assert "Aurelius v2 Status" in status_out
    assert "Skills:" in status_out


def test_cli_serve_command(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["aurelius", "serve", "--port", "8765"])
    assert cli.main_v2() == 0
    out = capsys.readouterr().out
    assert "8765" in out
    assert "Aurelius API server" in out


def test_api_surface_smoke() -> None:
    routes = {getattr(route, "path", "") for route in app.routes}
    assert "/api/health" in routes
    assert "/api/hardware/detect" in routes
    assert "/api/capabilities" in routes

    health = asyncio.run(api_health())
    assert health["status"] == "healthy"
    assert health["version"] == "2.0.0"
    assert "hardware" in health and "memory" in health

    hardware = asyncio.run(api_hardware_detect())
    assert "info" in hardware
    assert "profile" in hardware
    assert "recommended_models" in hardware
    assert isinstance(hardware["recommended_models"], dict)
