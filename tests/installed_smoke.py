"""Native installed-connector proof; no backend checkout, providers or real money.

Run with Python >=3.10 and uv on PATH:
    python -I mcp/tests/installed_smoke.py --receipt /owned/path/receipt.json
Every child receives an explicit environment, and its raw output is withheld.
"""

import argparse
import asyncio
from contextlib import redirect_stdout
import hashlib
from http.server import HTTPServer
import importlib.metadata
import importlib.util
import io
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import sys
import sysconfig
import tempfile
import threading
from unittest.mock import patch
import xml.etree.ElementTree as ET


TOOLS = {"find_work", "review_job", "claim_job", "submit_work", "job_status", "my_earnings", "read_messages", "send_message"}
EXPORT_NAMES = ("pyproject.toml", "requirements-certification.lock", "README.md", "mergepaid_mcp", "tests")
STAGES = {"source", "venv", "locked_dependencies", "wheel_build", "wheel_install", "stdio", "installed_tests"}


class ProofFailure(RuntimeError):
    """Child errors can expose only fixed stage and reason codes."""

    def __init__(self, stage, reason="failed"):
        if stage not in STAGES or reason not in {"failed", "timeout", "invalid_output", "incomplete", "missing"}:
            self.code = "proof_invalid_failure"
        else:
            self.code = stage + "_" + reason
        super().__init__(self.code)


def child_environment(work):
    """Keep only native process essentials; all config/cache/home belongs to us."""
    work = Path(work)
    environment = {key.upper(): value for key, value in os.environ.items()
                   if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "PATHEXT"}}
    environment.setdefault("PATH", os.defpath)
    for name in ("home", "tmp", "cache", "appdata", "localappdata"):
        (work / name).mkdir(parents=True, exist_ok=True)
    environment.update({
        "HOME": str(work / "home"), "USERPROFILE": str(work / "home"),
        "APPDATA": str(work / "appdata"), "LOCALAPPDATA": str(work / "localappdata"),
        "TMPDIR": str(work / "tmp"), "TEMP": str(work / "tmp"), "TMP": str(work / "tmp"),
        "PIP_CONFIG_FILE": os.devnull, "PIP_CACHE_DIR": str(work / "cache"),
        "PIP_KEYRING_PROVIDER": "disabled", "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "UV_NO_CONFIG": "1", "UV_CACHE_DIR": str(work / "cache"), "UV_PYTHON_DOWNLOADS": "never",
        "NETRC": str(work / "no-netrc"), "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1", "PYTHONHASHSEED": "0", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    })
    return environment


def terminate_owned(process, environment):
    """Terminate only this proof's process group/tree, including stdio children."""
    if os.name == "nt":
        system_root = environment.get("SYSTEMROOT") or environment.get("WINDIR")
        taskkill = Path(system_root or r"C:\Windows") / "System32" / "taskkill.exe"
        try:
            subprocess.run([str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                           env=environment, capture_output=True, timeout=15, check=False)
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=15)


def quiet_run(argv, *, stage, cwd, environment, timeout=300):
    options = {"start_new_session": True} if os.name != "nt" else {
        "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    try:
        process = subprocess.Popen(argv, cwd=cwd, env=environment, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, **options)
    except OSError:
        raise ProofFailure(stage, "missing") from None
    try:
        stdout, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        terminate_owned(process, environment)
        process.communicate(timeout=15)
        raise ProofFailure(stage, "timeout") from None
    except BaseException:
        terminate_owned(process, environment)
        raise
    if process.returncode:
        raise ProofFailure(stage) from None
    try:
        return stdout.decode("utf-8")
    except UnicodeDecodeError:
        raise ProofFailure(stage, "invalid_output") from None


def export_source(source, destination):
    destination.mkdir()
    for name in EXPORT_NAMES:
        path = source / name
        if not path.exists() or path.is_symlink():
            raise ProofFailure("source", "incomplete")
        if path.is_dir():
            if any(file.is_symlink() for file in path.rglob("*")):
                raise ProofFailure("source", "incomplete")
            shutil.copytree(path, destination / name,
                            ignore=shutil.ignore_patterns(".*", "__pycache__", "*.pyc"))
        else:
            shutil.copyfile(path, destination / name)


def source_snapshot(source):
    manifest = []
    for name in EXPORT_NAMES:
        path = source / name
        for file in sorted(path.rglob("*")) if path.is_dir() else [path]:
            relative = file.relative_to(source)
            if (file.is_file() and not any(part.startswith(".") or part == "__pycache__" for part in relative.parts)
                    and file.suffix != ".pyc"):
                manifest.append([relative.as_posix(), hashlib.sha256(file.read_bytes()).hexdigest()])
    return hashlib.sha256(json.dumps(sorted(manifest), separators=(",", ":")).encode()).hexdigest()


def load_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def teardown_owned_fixture(httpd, thread, owned_processes):
    """Attempt every owned resource before reporting any teardown failure."""
    incomplete = False
    for close in (httpd.shutdown, httpd.server_close):
        try:
            close()
        except Exception:
            incomplete = True
    try:
        thread.join(timeout=5)
        incomplete = thread.is_alive() or incomplete
    except Exception:
        incomplete = True
    for process in owned_processes:
        try:
            live = process.returncode is None
        except Exception:
            live = True
            incomplete = True
        if live:
            incomplete = True
            try:
                process.kill()
            except Exception:
                pass
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except Exception:
                pass
    if incomplete:
        raise ProofFailure("stdio", "incomplete")


async def stdio_probe(source, expected_version, work):
    from mcp import Client, StdioServerParameters, stdio_client
    import mcp.client.stdio as transport
    import mergepaid_mcp
    from mergepaid_mcp import server as installed_server

    if not sys.flags.isolated or "PYTHONPATH" in os.environ or list(Path.cwd().iterdir()):
        raise ProofFailure("stdio", "incomplete")
    if Path.cwd().resolve().is_relative_to(source):
        raise ProofFailure("stdio", "incomplete")

    package_path = Path(mergepaid_mcp.__file__).resolve()
    library = Path(sysconfig.get_path("purelib")).resolve()
    if not package_path.is_relative_to(library) or package_path.is_relative_to(source):
        raise ProofFailure("stdio", "incomplete")
    if not Path(installed_server.__file__).resolve().is_relative_to(library):
        raise ProofFailure("stdio", "incomplete")
    distribution = importlib.metadata.distribution("mergepaid-mcp")
    direct_url = json.loads(distribution.read_text("direct_url.json") or "{}")
    if (distribution.version != expected_version or direct_url.get("dir_info", {}).get("editable")
            or not direct_url.get("url", "").endswith(".whl")):
        raise ProofFailure("stdio", "incomplete")
    console = Path(sysconfig.get_path("scripts")) / ("mergepaid-mcp.exe" if os.name == "nt" else "mergepaid-mcp")
    if not console.is_file():
        raise ProofFailure("stdio", "missing")
    fixture = load_file("installed_stub_backend", source / "tests/stub_backend.py")
    class BoundedHandler(fixture.Handler):
        def setup(self):
            super().setup()
            self.connection.settimeout(30)

    httpd = HTTPServer(("127.0.0.1", 0), BoundedHandler)
    httpd.timeout = 1
    fixture.PORT = httpd.server_port
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    environment = child_environment(work)
    environment.update(MERGEPAID_API=f"http://127.0.0.1:{httpd.server_port}",
                       MERGEPAID_TOKEN="sup_test_token", MERGEPAID_SMOKE_BACKEND="stub")
    create_process = transport._create_platform_compatible_process
    owned_processes = []

    async def checked_process(*args, **kwargs):
        # The SDK merges its default env. Check the effective environment at
        # the real process boundary, then retain only the owned process handle.
        if kwargs.get("env") != environment:
            raise ProofFailure("stdio", "incomplete")
        process = await create_process(*args, **kwargs)
        owned_processes.append(process)
        return process

    thread.start()
    try:
        with patch.object(transport, "_create_platform_compatible_process", checked_process):
            # Check the isolated module route and the installed native executable.
            for command, arguments in ((sys.executable, ["-I", "-X", "utf8", "-m", "mergepaid_mcp.server"]),
                                       (str(console), [])):
                async with Client(stdio_client(StdioServerParameters(
                        command=command, args=arguments, env=environment)), raise_exceptions=True) as client:
                    if {tool.name for tool in (await client.list_tools()).tools} != TOOLS:
                        raise ProofFailure("stdio", "incomplete")
            # smoke.py reads only the synthetic fixture environment. Its full frozen
            # contract assertions are reused, with the installed console launcher.
            os.environ.clear()
            os.environ.update(environment)
            smoke = load_file("installed_contract_smoke", source / "tests/smoke.py")
            if set(smoke.TOOL_SPECS) != TOOLS:
                raise ProofFailure("stdio", "incomplete")

            def console_parameters(**_):
                return StdioServerParameters(command=str(console), args=[], env=environment)

            smoke.StdioServerParameters = console_parameters
            try:
                with redirect_stdout(io.StringIO()):
                    await smoke.main()
            finally:
                smoke.POSTER.close()
    finally:
        import anyio
        with anyio.CancelScope(shield=True):
            await teardown_owned_fixture(httpd, thread, owned_processes)
    return {"package_version": distribution.version, "installed_import_path": str(package_path),
            "installed_console_path": str(console), "editable": False,
            "isolated_module_list_tools": True, "console_list_tools": True,
            "console_eight_tool_contract": True, "human_approval_stays_separate": True,
            "tools": sorted(TOOLS), "fixture": "owned_ephemeral_loopback_stub",
            "effective_server_environment_verified": True, "owned_server_processes_reaped": len(owned_processes)}


async def bounded_stdio_probe(source, version, work):
    import anyio
    # Cancel within the probe first so the SDK can run its shielded, bounded
    # shutdown of its own native kill scopes. The parent timeout leaves room.
    with anyio.fail_after(120):
        return await stdio_probe(source, version, work)


TEST_RUNNER = """import sys
from mergepaid_mcp import server
sys.path.insert(0, sys.argv[1])
import pytest
class LegacyCases:
    def pytest_generate_tests(self, metafunc):
        cases = getattr(metafunc.function, 'cases', None)
        if cases is not None:
            names, values = cases
            metafunc.parametrize(','.join(names), values)
raise SystemExit(pytest.main(sys.argv[2:], plugins=[LegacyCases()]))
"""


def suite_receipt(path, output=None):
    try:
        root = ET.parse(path).getroot()
        cases = list(root.iter("testcase"))
        if not cases or any(list(root.iter(tag)) for tag in ("skipped", "failure", "error")):
            raise ProofFailure("installed_tests", "incomplete")
        suites = list(root.iter("testsuite"))
        # pytest 9 includes successful unittest subtests in its JUnit test total,
        # but emits one testcase node per top-level case. Bind both counts to
        # the completed run's summary, instead of dropping that evidence.
        subtests = 0
        if output is not None:
            passed = re.search(r"\b([1-9][0-9]*) passed\b", output)
            child_subtests = re.search(r"\b([1-9][0-9]*) subtests passed\b", output)
            subtests = int(child_subtests[1]) if child_subtests else 0
            if not passed or int(passed[1]) != len(cases) or re.search(r"\b[1-9][0-9]* skipped\b", output):
                raise ProofFailure("installed_tests", "incomplete")
        if (sum(int(suite.get("tests", "0")) for suite in suites) != len(cases) + subtests
                or any(int(suite.get(key, "0")) for suite in suites for key in ("skipped", "failures", "errors"))):
            raise ProofFailure("installed_tests", "incomplete")
    except (OSError, ET.ParseError, ValueError):
        raise ProofFailure("installed_tests", "invalid_output") from None
    return {"passed": len(cases), "subtests_passed": subtests, "skipped": 0, "legacy_parameter_cases": "included"}


def installed_proof(source, source_sha, receipt):
    # Spaces exercise native console-path handling without shell quoting.
    with tempfile.TemporaryDirectory(prefix="mergepaid native installed ") as temporary:
        work = Path(temporary).resolve()
        environment = child_environment(work)
        empty = work / "empty-cwd"
        empty.mkdir()
        candidate = work / "candidate"
        export_source(source, candidate)
        receipt.update(source_snapshot_sha256=source_snapshot(candidate),
                       certification_lock_sha256=hashlib.sha256((candidate / "requirements-certification.lock").read_bytes()).hexdigest())
        version = re.search(r'^version\s*=\s*"([^"\n]+)"\s*$',
                            (candidate / "pyproject.toml").read_text(), re.M)
        if not version:
            raise ProofFailure("source", "incomplete")
        git_sha = quiet_run(["git", "-C", str(source.parent), "rev-parse", "HEAD"],
                            stage="source", cwd=empty, environment=environment, timeout=15).strip()
        if not re.fullmatch(r"[0-9a-f]{40}", git_sha) or (source_sha and source_sha != git_sha):
            raise ProofFailure("source", "incomplete")
        dirty = quiet_run(["git", "-C", str(source.parent), "status", "--porcelain"],
                          stage="source", cwd=empty, environment=environment, timeout=15)
        receipt.update(source_sha=git_sha, source_checkout_dirty=bool(dirty.strip()))
        venv = work / "venv"
        quiet_run([sys.executable, "-I", "-X", "utf8", "-m", "venv", str(venv)],
                  stage="venv", cwd=empty, environment=environment, timeout=90)
        python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        uv = shutil.which("uv")
        if not uv:
            raise ProofFailure("locked_dependencies", "missing")
        quiet_run([uv, "pip", "install", "--python", str(python), "--index-url", "https://pypi.org/simple",
                   "--only-binary", ":all:", "--require-hashes", "--no-deps", "-r",
                   str(candidate / "requirements-certification.lock")],
                  stage="locked_dependencies", cwd=empty, environment=environment)
        wheel_dir = work / "wheels"
        quiet_run([str(python), "-I", "-X", "utf8", "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
                   "--wheel-dir", str(wheel_dir), str(candidate)],
                  stage="wheel_build", cwd=empty, environment=environment)
        wheels = list(wheel_dir.glob("mergepaid_mcp-*.whl"))
        if len(wheels) != 1:
            raise ProofFailure("wheel_build", "incomplete")
        receipt.update(wheel_sha256=hashlib.sha256(wheels[0].read_bytes()).hexdigest(), wheel_name=wheels[0].name)
        quiet_run([str(python), "-I", "-X", "utf8", "-m", "pip", "install", "--no-deps", "--no-build-isolation", str(wheels[0])],
                  stage="wheel_install", cwd=empty, environment=environment)
        driver = candidate / "tests/installed_smoke.py"
        output = quiet_run([str(python), "-I", "-X", "utf8", str(driver), "--probe", str(candidate), version[1], str(work)],
                           stage="stdio", cwd=empty, environment=environment, timeout=180)
        try:
            receipt.update(json.loads(output))
        except (json.JSONDecodeError, TypeError, ValueError):
            raise ProofFailure("stdio", "invalid_output") from None
        # The inserted namespace parent has tests/README/pyproject only, never server
        # code; the version test binds the installed server to the built pyproject.
        test_copy = work / "suite"
        test_copy.mkdir()
        shutil.copytree(candidate / "tests", test_copy / "tests")
        for name in ("README.md", "pyproject.toml"):
            shutil.copyfile(candidate / name, test_copy / name)
        junit = work / "installed-tests.xml"
        print("NOT-APPLICABLE: test_local_seed requires the deliberately excluded full-backend fixture", flush=True)
        output = quiet_run([str(python), "-I", "-X", "utf8", "-c", TEST_RUNNER, str(test_copy), str(test_copy / "tests"),
                   "-q", "-ra", "--import-mode=prepend", "-p", "no:cacheprovider",
                   "--ignore=" + str(test_copy / "tests/test_local_seed.py"), "--junitxml=" + str(junit)],
                  stage="installed_tests", cwd=empty, environment=environment)
        receipt["installed_tests"] = suite_receipt(junit, output)
        receipt["not_applicable"] = [{"file": "tests/test_local_seed.py", "reason": "full_backend_deliberately_excluded"}]
        receipt.update(empty_cwd=True, python_isolated=True, inherited_pythonpath=False,
                       owned_fixture_and_process_cleanup=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--source-sha", default="")
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--probe", nargs=3, metavar=("SOURCE", "VERSION", "WORK"), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.probe:
        try:
            source, version, work = args.probe
            print(json.dumps(asyncio.run(bounded_stdio_probe(Path(source).resolve(), version, Path(work)))))
        except Exception:
            print("FAIL: stdio_failed", file=sys.stderr)
            return 1
        return 0
    receipt = {"evidence": "native_standalone_installed_connector", "status": "failed",
               "os": platform.system(), "platform": platform.platform(), "python": platform.python_version(),
               "external_providers": False, "external_payments": False}
    try:
        installed_proof(args.source.resolve(), args.source_sha, receipt)
        receipt["status"] = "passed"
    except ProofFailure as failure:
        receipt["failure_code"] = failure.code
    except Exception:
        receipt["failure_code"] = "proof_unexpected_failure"
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
