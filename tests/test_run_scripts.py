from pathlib import Path
import os
import re
import subprocess
import sys


SCRIPTS = Path("scripts")


def _text(name: str) -> str:
    return (SCRIPTS / name).read_text(encoding="utf-8")


def _last_nonempty_line(name: str) -> str:
    lines = [ln.strip() for ln in _text(name).splitlines() if ln.strip()]
    return lines[-1]


def test_cmd_wrappers_end_on_powershell_so_ctrl_c_skips_yn_prompt():
    for name in ("run.cmd", "run-server.cmd"):
        body = _text(name)
        assert "STOCK_ANALYZER_KEEP_WINDOW=1" in body
        assert _last_nonempty_line(name).lower().startswith("powershell ")
        after_ps = body.lower().split("powershell -noprofile", 1)[1]
        assert "pause" not in after_ps
        assert "exit /b" not in after_ps


def test_run_ps1_starts_server_in_process():
    body = _text("run.ps1")
    assert "& $serverPs1" in body
    assert "powershell.exe -NoProfile -ExecutionPolicy Bypass -File $serverPs1" not in body


def test_run_server_handles_ctrl_c_and_window_close():
    body = _text("run-server.ps1")
    assert "SetConsoleCtrlHandler" in body
    assert "CTRL_CLOSE" in body
    assert "JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE" in body
    assert "DisableQuickEdit" in body
    assert "KillChild" in body
    assert "Wait-KeepWindow" in body
    assert "StopRequested" in body
    assert "data\\run\\server.pid" in body
    assert "Initialize-SaRunHost" in body
    assert "AssignPidToJob" in body
    onctrl = body.split("public static bool OnCtrl", 1)[1].split("public static void Register", 1)[0]
    assert "CTRL_CLOSE" in onctrl
    assert "KillChild()" not in onctrl
    assert "AssignPidToJob($script:JobHandle" not in body
    assert "WindowStyle Hidden" in body
    assert "-NoNewWindow" not in body
    assert "src.market.clock_git" in body
    assert "Invoke-ClockGitFlush" in body


def test_sarunhost_compiles_and_job_kills_child(tmp_path):
    if os.name != "nt":
        return
    body = _text("run-server.ps1")
    match = re.search(r'\$saRunHostSrc = @"\n(.*)\n"@', body, re.S)
    assert match, "SaRunHost C# source missing"
    cs = tmp_path / "SaRunHost.cs"
    cs.write_text(match.group(1).replace("\r\n", "\n"), encoding="utf-8")
    py = Path(sys.executable)
    ps1 = tmp_path / "check.ps1"
    ps1.write_text(
        "\n".join(
            [
                "$ErrorActionPreference = 'Stop'",
                "Add-Type -Path '" + str(cs).replace("'", "''") + "'",
                "$job = [SaRunHost]::CreateKillOnCloseJob()",
                "if ($job -eq [IntPtr]::Zero) { throw 'CreateKillOnCloseJob failed' }",
                "$p = Start-Process -FilePath '"
                + str(py).replace("'", "''")
                + "' -ArgumentList '-c','import time; time.sleep(30)' -WindowStyle Hidden -PassThru",
                "if (-not [SaRunHost]::AssignPidToJob($job, [int]$p.Id)) {",
                "  try { Stop-Process -Id $p.Id -Force } catch {}",
                "  throw 'AssignPidToJob failed'",
                "}",
                "[SaRunHost]::CloseJob($job)",
                "$dead = $p.WaitForExit(5000)",
                "if (-not $dead) {",
                "  try { Stop-Process -Id $p.Id -Force } catch {}",
                "  throw 'child still alive after job close'",
                "}",
                "Write-Output 'OK'",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    ran = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ps1),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert ran.returncode == 0, ran.stdout + "\n" + ran.stderr
    assert "OK" in ran.stdout
