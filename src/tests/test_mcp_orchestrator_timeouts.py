from datetime import datetime
import json

from orchestration.mcp_orchestrator import MCPConnection, MCPOrchestrator, MCPServerConfig


def test_compute_initialize_timeout_respects_server_budget() -> None:
    config = MCPServerConfig(
        name="google-workspace",
        command="dummy",
        args=[],
        startup_grace=10,
        tool_timeout=60.0,
    )

    timeout = MCPOrchestrator._compute_initialize_timeout(config)

    assert timeout == 30.0


def test_compute_initialize_timeout_has_reasonable_floor() -> None:
    config = MCPServerConfig(
        name="fast-server",
        command="dummy",
        args=[],
        startup_grace=1,
        tool_timeout=6.0,
    )

    timeout = MCPOrchestrator._compute_initialize_timeout(config)

    assert timeout == 10.0


def test_compute_list_tools_timeout_respects_server_budget() -> None:
    config = MCPServerConfig(
        name="google-workspace",
        command="dummy",
        args=[],
        startup_grace=10,
        tool_timeout=60.0,
    )
    connection = object.__new__(MCPConnection)
    connection.LIST_TOOLS_TIMEOUT = 10.0

    timeout = MCPOrchestrator._compute_list_tools_timeout(config, connection)

    assert timeout == 30.0


def test_compute_list_tools_timeout_defaults_to_connection_timeout_without_config() -> None:
    connection = object.__new__(MCPConnection)
    connection.LIST_TOOLS_TIMEOUT = 10.0

    timeout = MCPOrchestrator._compute_list_tools_timeout(None, connection)

    assert timeout == 10.0


def test_get_available_tools_skips_unhealthy_servers_without_listing() -> None:
    orchestrator = object.__new__(MCPOrchestrator)
    connection = object.__new__(MCPConnection)
    connection.LIST_TOOLS_TIMEOUT = 10.0
    connection.list_tools = lambda timeout=None: ["get_events"]

    class _Proc:
        @staticmethod
        def poll():
            return None

    unhealthy_server = type(
        "Server",
        (),
        {
            "process": _Proc(),
            "health_status": "unhealthy",
            "started_at": datetime.now(),
        },
    )()

    orchestrator.connections = {"google-workspace": connection}
    orchestrator.servers = {"google-workspace": unhealthy_server}
    orchestrator.configs = {
        "google-workspace": MCPServerConfig(
            name="google-workspace",
            command="dummy",
            args=[],
            tool_timeout=60.0,
        )
    }

    tools = orchestrator.get_available_tools()

    assert tools == {"google-workspace": []}


def test_get_status_includes_callme_runtime_status(tmp_path, monkeypatch) -> None:
    status_path = tmp_path / "callme_runtime_status.json"
    status_path.write_text(
        json.dumps(
            {
                "phase": "ready",
                "tunnel_kind": "localtunnel",
                "public_url": "https://example.loca.lt",
                "connected": True,
                "degraded": True,
                "degraded_reason": "ngrok_contention_cooldown",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CALLME_RUNTIME_STATUS_PATH", str(status_path))

    orchestrator = object.__new__(MCPOrchestrator)

    class _Proc:
        @staticmethod
        def poll():
            return None

        pid = 1234

    server = type(
        "Server",
        (),
        {
            "process": _Proc(),
            "health_status": "healthy",
            "started_at": datetime.now(),
            "restart_count": 0,
            "last_health_check": None,
        },
    )()

    orchestrator.servers = {"call-me": server}
    orchestrator.connections = {}
    orchestrator._starting_servers = set()
    orchestrator.configs = {
        "call-me": MCPServerConfig(
            name="call-me",
            command="dummy",
            args=[],
            categories=["phone"],
            description="Phone",
        )
    }

    status = orchestrator.get_status()
    callme = status["servers"]["call-me"]

    assert callme["runtime_status"]["tunnel_kind"] == "localtunnel"
    assert callme["runtime_status"]["degraded"] is True
    assert "degraded tunnel mode via localtunnel" in callme["warning"]
    assert callme["health"] == "healthy"
    assert callme["effective_health"] == "healthy"
    assert callme["health_source"] == "mcp"


def test_get_status_promotes_callme_effective_health_from_runtime_status(tmp_path, monkeypatch) -> None:
    status_path = tmp_path / "callme_runtime_status.json"
    status_path.write_text(
        json.dumps(
            {
                "phase": "ready",
                "tunnel_kind": "localtunnel",
                "public_url": "https://example.loca.lt",
                "connected": True,
                "degraded": True,
                "degraded_reason": "ngrok_contention",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CALLME_RUNTIME_STATUS_PATH", str(status_path))

    orchestrator = object.__new__(MCPOrchestrator)

    class _Proc:
        @staticmethod
        def poll():
            return None

        pid = 1234

    server = type(
        "Server",
        (),
        {
            "process": _Proc(),
            "health_status": "unknown",
            "started_at": datetime.now(),
            "restart_count": 0,
            "last_health_check": None,
        },
    )()

    orchestrator.servers = {"call-me": server}
    orchestrator.connections = {}
    orchestrator._starting_servers = {"call-me"}
    orchestrator.configs = {
        "call-me": MCPServerConfig(
            name="call-me",
            command="dummy",
            args=[],
        )
    }

    status = orchestrator.get_status()
    callme = status["servers"]["call-me"]

    assert callme["health"] == "unknown"
    assert callme["effective_health"] == "healthy"
    assert callme["health_source"] == "runtime_status"
