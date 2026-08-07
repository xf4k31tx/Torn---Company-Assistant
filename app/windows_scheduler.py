from __future__ import annotations

import csv
import datetime
import getpass
import html
import os
import subprocess
import sys
import tempfile
from pathlib import Path

TASK_NAME = "Torn Company Assistant - Daily Income"
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def scheduled_command(
    executable: str | None = None,
    frozen: bool | None = None,
) -> tuple[str, list[str]]:
    exe = executable or sys.executable
    is_frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    if is_frozen:
        return exe, ["--scheduled-daily-income"]
    return exe, [str(PROJECT_ROOT / "main.py"), "--scheduled-daily-income"]


def _identity() -> str:
    domain = os.environ.get("USERDOMAIN", "").strip()
    user = getpass.getuser()
    return f"{domain}\\{user}" if domain else user


def build_task_xml(
    executable: str,
    arguments: list[str],
    wake_computer: bool = False,
    start: datetime.datetime | None = None,
    user_id: str | None = None,
) -> str:
    start = start or datetime.datetime.now().replace(second=0, microsecond=0)
    command = html.escape(str(executable))
    args = html.escape(subprocess.list2cmdline(arguments))
    user = html.escape(user_id or _identity())
    wake = str(bool(wake_computer)).lower()
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Updates Torn Company Assistant rolling income data.</Description></RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <Repetition><Interval>PT1H</Interval><Duration>P1D</Duration><StopAtDurationEnd>false</StopAtDurationEnd></Repetition>
      <StartBoundary>{start.isoformat()}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author"><UserId>{user}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <StartWhenAvailable>true</StartWhenAvailable>
    <WakeToRun>{wake}</WakeToRun>
    <ExecutionTimeLimit>PT30M</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author"><Exec><Command>{command}</Command><Arguments>{args}</Arguments></Exec></Actions>
</Task>"""


def _run(args: list[str]) -> subprocess.CompletedProcess:
    if os.name != "nt":
        raise RuntimeError("Windows scheduled collection is available only on Windows.")
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def install_task(wake_computer: bool = False) -> None:
    executable, arguments = scheduled_command()
    xml = build_task_xml(executable, arguments, wake_computer=wake_computer)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", encoding="utf-16", delete=False
        ) as handle:
            handle.write(xml)
            temp_path = handle.name
        result = _run([
            "schtasks.exe", "/Create", "/TN", TASK_NAME,
            "/XML", temp_path, "/F",
        ])
        if result.returncode:
            raise RuntimeError((result.stderr or result.stdout).strip())
    finally:
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)


def remove_task() -> None:
    result = _run(["schtasks.exe", "/Delete", "/TN", TASK_NAME, "/F"])
    if result.returncode and "cannot find" not in (
        (result.stderr or result.stdout).lower()
    ):
        raise RuntimeError((result.stderr or result.stdout).strip())


def set_task_enabled(enabled: bool) -> None:
    switch = "/ENABLE" if enabled else "/DISABLE"
    result = _run(["schtasks.exe", "/Change", "/TN", TASK_NAME, switch])
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip())


def task_status() -> dict:
    result = _run([
        "schtasks.exe", "/Query", "/TN", TASK_NAME,
        "/FO", "CSV", "/V", "/NH",
    ])
    if result.returncode:
        return {
            "installed": False,
            "status": "Not installed",
            "last_run": "",
            "next_run": "",
            "last_result": "",
        }
    rows = list(csv.reader(result.stdout.splitlines()))
    row = rows[0] if rows else []
    return {
        "installed": True,
        "next_run": row[2] if len(row) > 2 else "",
        "status": row[3] if len(row) > 3 else "Installed",
        "last_run": row[5] if len(row) > 5 else "",
        "last_result": row[6] if len(row) > 6 else "",
    }


def repair_task(wake_computer: bool = False) -> dict:
    install_task(wake_computer=wake_computer)
    return task_status()
