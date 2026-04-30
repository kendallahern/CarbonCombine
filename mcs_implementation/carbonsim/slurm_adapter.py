from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
import subprocess
import time


@dataclass(frozen=True)
class SlurmJobRequest:
    cluster_name: str
    job_name: str
    nodes: int
    slot_minutes: int
    script_path: str
    output_path: str | None = None
    error_path: str | None = None
    checkpoint_path: str | None = None
    partition: str | None = None
    chdir: str | None = None


@dataclass(frozen=True)
class SlurmJobHandle:
    job_id: str
    cluster_name: str
    job_name: str


@dataclass(frozen=True)
class SlurmJobResult:
    job_id: str
    cluster_name: str
    state: str
    exit_code: int
    work_completed: float


class SlurmAdapter(Protocol):
    def submit_slot_job(self, request: SlurmJobRequest) -> SlurmJobHandle:
        ...

    def wait_for_job(self, handle: SlurmJobHandle) -> SlurmJobResult:
        ...

    def read_job_progress(self, handle: SlurmJobHandle) -> float:
        ...


class MockSlurmAdapter:
    def __init__(self) -> None:
        self._counter = 0

    def submit_slot_job(self, request: SlurmJobRequest) -> SlurmJobHandle:
        self._counter += 1
        job_id = f"mock-{self._counter}"
        return SlurmJobHandle(
            job_id=job_id,
            cluster_name=request.cluster_name,
            job_name=request.job_name,
        )

    def wait_for_job(self, handle: SlurmJobHandle) -> SlurmJobResult:
        return SlurmJobResult(
            job_id=handle.job_id,
            cluster_name=handle.cluster_name,
            state="COMPLETED",
            exit_code=0,
            work_completed=0.0,
        )

    def read_job_progress(self, handle: SlurmJobHandle) -> float:
        return 0.0


class DockerComposeSlurmAdapter:
    """
    Real Slurm adapter that talks to Slurm inside a Docker Compose service.

    Workflow:
    - copy host sbatch script into the container
    - run sbatch inside the service container
    - poll squeue until job disappears
    - query sacct for final state
    """

    def __init__(
        self,
        compose_project_dir: str,
        service_name: str = "slurmctld",
        worker_service_names: list[str] | None = None,
        poll_interval_seconds: float = 2.0,
        sacct_wait_seconds: float = 3.0,
        remote_job_dir: str = "/tmp/mcs_jobs",
    ) -> None:
        self.compose_project_dir = str(Path(compose_project_dir).resolve())
        self.service_name = service_name
        self.worker_service_names = worker_service_names or ["cpu-worker"]
        self.poll_interval_seconds = poll_interval_seconds
        self.sacct_wait_seconds = sacct_wait_seconds
        self.remote_job_dir = remote_job_dir

    def submit_slot_job(self, request: SlurmJobRequest) -> SlurmJobHandle:
        script_path = Path(request.script_path).resolve()
        if not script_path.exists():
            raise FileNotFoundError(f"Slurm script not found: {script_path}")

        remote_script_path = f"{self.remote_job_dir}/{script_path.name}"

        self._exec_in_service(["mkdir", "-p", self.remote_job_dir])
        self._compose_cp_to_service(str(script_path), remote_script_path)

        cmd = ["sbatch", "--parsable"]
        if request.partition:
            cmd.extend(["--partition", request.partition])
        if request.chdir:
            cmd.extend(["--chdir", request.chdir])
        cmd.append(remote_script_path)

        proc = self._exec_in_service(cmd, capture_output=True)

        stdout = proc.stdout.strip()
        if not stdout:
            raise RuntimeError("sbatch returned empty output")

        job_id = stdout.split(";")[0].strip()
        if not job_id:
            raise RuntimeError(f"Unable to parse sbatch job id from output: {stdout!r}")

        return SlurmJobHandle(
            job_id=job_id,
            cluster_name=request.cluster_name,
            job_name=request.job_name,
        )

    def wait_for_job(self, handle: SlurmJobHandle) -> SlurmJobResult:
        while True:
            queue_state = self._query_squeue_state(handle.job_id)
            if queue_state is None:
                break
            time.sleep(self.poll_interval_seconds)

        deadline = time.time() + max(self.sacct_wait_seconds, 0.0)
        last_error: Exception | None = None

        while True:
            try:
                result = self._query_sacct_result(handle)
                if result is not None:
                    return result
            except Exception as exc:
                last_error = exc

            if time.time() >= deadline:
                break
            time.sleep(0.5)

        if last_error:
            raise RuntimeError(
                f"Job {handle.job_id} disappeared from squeue but sacct did not return a result"
            ) from last_error

        raise RuntimeError(
            f"Job {handle.job_id} disappeared from squeue but sacct did not return a result"
        )

    def read_job_progress(self, handle: SlurmJobHandle) -> float:
        return 0.0
    
    def copy_file_to_service(self, host_path: str, remote_path: str) -> None:
        host = Path(host_path).resolve()
        if not host.exists():
            raise FileNotFoundError(f"Host file not found: {host}")

        services = [self.service_name] + self.worker_service_names
        remote_parent = str(Path(remote_path).parent)

        for service in services:
            self._exec_in_specific_service(service, ["mkdir", "-p", remote_parent])
            self._compose_cp_to_specific_service(str(host), service, remote_path)

    def _query_squeue_state(self, job_id: str) -> str | None:
        proc = self._exec_in_service(
            ["squeue", "--noheader", "--jobs", job_id, "--format=%T"],
            check=False,
            capture_output=True,
        )

        if proc.returncode != 0:
            stderr = proc.stderr.strip()
            raise RuntimeError(f"squeue failed for job {job_id}: {stderr}")

        state = proc.stdout.strip()
        if not state:
            return None
        return state.splitlines()[0].strip()

    def _query_sacct_result(self, handle: SlurmJobHandle) -> SlurmJobResult | None:
        proc = self._exec_in_service(
            [
                "sacct",
                "--noheader",
                "--parsable2",
                "--jobs",
                handle.job_id,
                "--format=JobIDRaw,State,ExitCode",
            ],
            check=False,
            capture_output=True,
        )

        if proc.returncode != 0:
            stderr = proc.stderr.strip()
            raise RuntimeError(f"sacct failed for job {handle.job_id}: {stderr}")

        lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        if not lines:
            return None

        chosen: tuple[str, str, str] | None = None
        for line in lines:
            parts = line.split("|")
            if len(parts) < 3:
                continue
            job_id_raw, state, exit_code = parts[0].strip(), parts[1].strip(), parts[2].strip()
            if job_id_raw == handle.job_id:
                chosen = (job_id_raw, state, exit_code)
                break

        if chosen is None:
            parts = lines[0].split("|")
            if len(parts) < 3:
                raise RuntimeError(f"Unexpected sacct output for job {handle.job_id}: {lines!r}")
            chosen = (parts[0].strip(), parts[1].strip(), parts[2].strip())

        _, state, exit_code_text = chosen
        exit_code = self._parse_exit_code(exit_code_text)

        return SlurmJobResult(
            job_id=handle.job_id,
            cluster_name=handle.cluster_name,
            state=state,
            exit_code=exit_code,
            work_completed=0.0,
        )

    def _compose_base_cmd(self) -> list[str]:
        return ["docker", "compose", "--project-directory", self.compose_project_dir]

    def _exec_in_service(
        self,
        inner_cmd: list[str],
        check: bool = True,
        capture_output: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        cmd = self._compose_base_cmd() + ["exec", "-T", self.service_name] + inner_cmd
        return subprocess.run(
            cmd,
            check=check,
            capture_output=capture_output,
            text=True,
        )

    def _compose_cp_to_service(self, host_path: str, remote_path: str) -> None:
        target = f"{self.service_name}:{remote_path}"
        cmd = self._compose_base_cmd() + ["cp", host_path, target]
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
        )

    def _exec_in_specific_service(
        self,
        service: str,
        inner_cmd: list[str],
        check: bool = True,
        capture_output: bool = False,
    ):
        # Map service -> actual container name
        if service == "slurmctld":
            container = "slurmctld"
        elif service == "cpu-worker":
            container = "slurm-docker-cluster-cpu-worker-1"
        else:
            container = service

        cmd = ["docker", "exec", container] + inner_cmd

        return subprocess.run(
            cmd,
            check=check,
            capture_output=capture_output,
            text=True,
        )

    def _compose_cp_to_specific_service(self, host_path: str, service: str, remote_path: str) -> None:
        if service == "cpu-worker":
            container = "slurm-docker-cluster-cpu-worker-1"
        elif service == "slurmctld":
            container = "slurmctld"
        else:
            container = service

        target = f"{container}:{remote_path}"

        cmd = ["docker", "cp", host_path, target]

        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
        )

    @staticmethod
    def _parse_exit_code(exit_code_text: str) -> int:
        base = exit_code_text.split(":")[0].strip()
        try:
            return int(base)
        except ValueError as exc:
            raise RuntimeError(f"Could not parse Slurm exit code: {exit_code_text!r}") from exc


def ensure_parent_dir(path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
