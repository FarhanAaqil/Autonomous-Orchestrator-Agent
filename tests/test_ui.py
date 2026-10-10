"""
tests/test_ui.py

Tests for UI endpoint serving and static assets in Orchestrator Agent v2.
"""

from fastapi.testclient import TestClient

from orchestrator_core.main import app


def test_ui_root_serves_html():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "Orchestrator Agent" in response.text
    assert 'id="root"' in response.text


def test_ui_path_serves_html():
    client = TestClient(app)
    response = client.get("/ui")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "Orchestrator Agent" in response.text


def test_ui_contains_all_phase8_views_and_navigation():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    html = response.text

    # View components defined
    assert "function JobsView" in html
    assert "function SchedulesView" in html
    assert "function MemoryView" in html
    assert "function SettingsView" in html
    assert "function EvalView" in html
    assert "function DiagnosticsView" in html
    assert "function DispatchView" in html
    assert "function ConnectionStatusBadge" in html

    # Navigation items present
    assert "Jobs Timeline" in html
    assert "Schedules" in html
    assert "Memory" in html
    assert "Settings" in html
    assert "Benchmark" in html


def test_ui_contains_sticky_bottom_scroll_and_pill():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    html = response.text

    # Sticky-bottom scroll via IntersectionObserver and sentinel
    assert "IntersectionObserver" in html
    assert "messagesEndRef" in html
    assert "chatContainerRef" in html
    assert "isPinned" in html
    assert "Jump to latest ↓" in html


def test_ui_contains_sse_reconnect_and_last_event_id():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    html = response.text

    # SSE reconnection with backoff and Last-Event-ID
    assert "subscribeJobEvents" in html
    assert "last_event_id=" in html
    assert "lastEventId" in html
    assert "retryDelay" in html
    assert "job.created" in html
    assert "job.step" in html
    assert "agent.status" in html


def test_ui_contains_jobs_timeline_and_step_telemetry():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    html = response.text

    # Jobs timeline features
    assert "getJobs" in html
    assert "getJobSteps" in html
    assert "cancelJob" in html
    assert "answerJob" in html
    assert "createJob" in html
    assert "Execution Step Trace" in html
    assert "latency_ms" in html
    assert "output_data" in html
    assert "input_data" in html


def test_ui_contains_schedules_crud_and_run_now():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    html = response.text

    # Schedules CRUD and run now
    assert "getSchedules" in html
    assert "createSchedule" in html
    assert "updateSchedule" in html
    assert "deleteSchedule" in html
    assert "runSchedule" in html
    assert "Run Now" in html
    assert "cron_expr" in html


def test_ui_contains_memory_queue_and_summarize():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    html = response.text

    # Memory UI features
    assert "getMemories" in html
    assert "createMemory" in html
    assert "updateMemory" in html
    assert "confirmMemory" in html
    assert "deleteMemory" in html
    assert "summarizeSession" in html
    assert "Pending Review" in html
    assert "Summarize Session" in html


def test_ui_contains_settings_kill_switch_and_budget():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    html = response.text

    # Settings features
    assert "getSystemFlags" in html
    assert "toggleKillSwitch" in html
    assert "setDailyBudget" in html
    assert "Emergency Kill Switch" in html
    assert "Daily Budget Ceiling" in html
    assert "Silver Shade Selector" in html or "silverShade" in html


def test_ui_contains_agent_roster_toggle():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    html = response.text

    # Administrative enable/disable toggle
    assert "updateAgent" in html
    assert "is_active" in html
    assert "Fleet Roster" in html

