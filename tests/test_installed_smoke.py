"""Fail-closed proof boundaries, using synthetic environments and receipts only."""

import asyncio
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

try:
    import pytest
except ModuleNotFoundError as exc:
    if exc.name != "pytest":
        raise
    # pytest is an optional certification dependency, not part of the connector
    # runtime. These function/fixture tests are executed by installed certification.
    import unittest
    raise unittest.SkipTest("pytest-only certification tests require the optional pytest dependency")

from tests import installed_smoke as proof


def test_child_environment_keeps_native_essentials_and_replaces_ambient_configuration(tmp_path):
    poisoned = {name: "synthetic-ambient-value" for name in (
        "MERGEPAID_TOKEN", "GITHUB_TOKEN", "STRIPE_TEST_SECRET_KEY", "HTTP_PROXY", "HTTPS_PROXY",
        "ALL_PROXY", "PYTHONPATH", "PYTHONSTARTUP", "PYTEST_ADDOPTS", "BASH_ENV", "ENV",
        "SSH_AUTH_SOCK", "UV_INDEX_URL", "PIP_INDEX_URL", "HOME", "TEMP", "TMP", "APPDATA")}
    poisoned.update(PATH=os.defpath, SystemRoot=r"C:\Windows", PATHEXT=".COM;.EXE;.BAT;.CMD")
    with patch.dict(os.environ, poisoned, clear=True):
        environment = proof.child_environment(tmp_path)
    assert environment["PATH"] == os.defpath
    assert environment["SYSTEMROOT"] == r"C:\Windows"
    assert environment["PATHEXT"] == ".COM;.EXE;.BAT;.CMD"
    assert not {key.upper() for key in poisoned}.intersection(environment) - {
        "PATH", "SYSTEMROOT", "PATHEXT", "HOME", "TEMP", "TMP", "APPDATA"}
    assert all(value != "synthetic-ambient-value" for value in environment.values())
    assert Path(environment["TEMP"]).is_relative_to(tmp_path)
    assert Path(environment["HOME"]).is_relative_to(tmp_path)
    assert "PYTHONPATH" not in environment


@pytest.mark.parametrize("xml", [
    "<testsuites/>",
    '<testsuite tests="1" skipped="1"><testcase><skipped/></testcase></testsuite>',
    '<testsuite tests="1" failures="1"><testcase><failure/></testcase></testsuite>',
    '<testsuite tests="1" errors="1"><testcase><error/></testcase></testsuite>',
    '<testsuite tests="2"><testcase/></testsuite>',
    '<testsuite tests="1" skipped="1"><testcase/></testsuite>',
    "invalid synthetic output",
])
def test_suite_cannot_certify_skips_failures_empty_or_malformed_output(tmp_path, xml):
    result = tmp_path / "result.xml"
    result.write_text(xml)
    with pytest.raises(proof.ProofFailure):
        proof.suite_receipt(result)


def test_suite_counts_all_parameter_cases(tmp_path):
    result = tmp_path / "result.xml"
    result.write_text('<testsuites><testsuite tests="2" skipped="0" errors="0" failures="0">'
                      '<testcase name="case_a"/><testcase name="case_b"/></testsuite></testsuites>')
    assert proof.suite_receipt(result) == {"passed": 2, "subtests_passed": 0,
                                         "skipped": 0, "legacy_parameter_cases": "included"}


def test_pytest_subtest_totals_require_matching_success_summary(tmp_path):
    result = tmp_path / "result.xml"
    result.write_text('<testsuite tests="3" skipped="0" errors="0" failures="0">'
                      '<testcase name="case_a"/><testcase name="case_b"/></testsuite>')
    assert proof.suite_receipt(result, "2 passed, 1 subtests passed") == {
        "passed": 2, "subtests_passed": 1, "skipped": 0, "legacy_parameter_cases": "included"}
    for summary in ("2 passed", "1 passed, 2 subtests passed", "2 passed, 1 skipped, 1 subtests passed"):
        with pytest.raises(proof.ProofFailure):
            proof.suite_receipt(result, summary)


def test_failed_child_output_is_withheld(tmp_path, capsys):
    environment = proof.child_environment(tmp_path)
    with pytest.raises(proof.ProofFailure, match="stdio_failed"):
        proof.quiet_run([sys.executable, "-I", "-c",
                         "print('SYNTHETIC_CHILD_VALUE'); raise SystemExit(1)"],
                        stage="stdio", cwd=tmp_path, environment=environment, timeout=10)
    assert "SYNTHETIC_CHILD_VALUE" not in capsys.readouterr().out


def test_timeout_terminates_owned_child(tmp_path):
    environment = proof.child_environment(tmp_path)
    owned = subprocess.Popen([sys.executable, "-I", "-c", "import time; time.sleep(30)"],
                             env=environment,
                             start_new_session=os.name != "nt",
                             creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0)
    try:
        proof.terminate_owned(owned, environment)
        assert owned.poll() is not None
    finally:
        if owned.poll() is None:
            owned.kill()
            owned.wait(timeout=10)


def test_quiet_run_timeout_fails_and_reaps_only_its_owned_process(tmp_path):
    environment = proof.child_environment(tmp_path)
    real_popen = subprocess.Popen
    owned = []

    def capture(*args, **kwargs):
        child = real_popen(*args, **kwargs)
        owned.append(child)
        return child

    with patch.object(proof.subprocess, "Popen", capture):
        with pytest.raises(proof.ProofFailure, match="stdio_timeout"):
            proof.quiet_run([sys.executable, "-I", "-c", "import time; time.sleep(30)"],
                            stage="stdio", cwd=tmp_path, environment=environment, timeout=0.1)
    assert owned[0].poll() is not None


@pytest.mark.parametrize("first_kill_fails", [False, True])
def test_teardown_attempts_both_live_handles_despite_thread_or_process_failure(first_kill_fails):
    events = []

    class Fixture:
        def shutdown(self):
            events.append("shutdown")

        def server_close(self):
            events.append("server_close")

    class Thread:
        def join(self, timeout):
            assert timeout == 5
            events.append("join")

        def is_alive(self):
            return True

    class Process:
        def __init__(self, name, kill_fails=False):
            self.name = name
            self.kill_fails = kill_fails
            self.returncode = None

        def kill(self):
            events.append("kill_" + self.name)
            if self.kill_fails:
                raise RuntimeError("synthetic teardown failure")

        async def wait(self):
            events.append("wait_" + self.name)
            self.returncode = -9

    handles = [Process("first", first_kill_fails), Process("second")]
    with pytest.raises(proof.ProofFailure, match="stdio_incomplete"):
        asyncio.run(proof.teardown_owned_fixture(Fixture(), Thread(), handles))
    assert events == ["shutdown", "server_close", "join", "kill_first", "wait_first", "kill_second", "wait_second"]
    assert all(handle.returncode is not None for handle in handles)


def test_failure_codes_never_echo_arbitrary_child_details():
    assert str(proof.ProofFailure("synthetic_child_value", "synthetic_reason")) == "proof_invalid_failure"
