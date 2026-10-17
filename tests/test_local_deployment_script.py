import os
import subprocess
from pathlib import Path


ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "docker-compose.yml").exists()
)


def test_root_deploy_script_is_executable_and_resolves_its_project_root():
    script_path = ROOT / "deploy/k8s/one-click-deploy.sh"
    assert script_path.exists()
    assert script_path.stat().st_mode & 0o111
    script = script_path.read_text(encoding="utf-8")
    assert 'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"' in script
    assert 'PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"' in script
    assert 'cd "${PROJECT_ROOT}"' in script
    assert 'PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"' in script


def test_deploy_script_builds_images_then_deploys_to_kubernetes():
    script = (ROOT / "deploy/k8s/one-click-deploy.sh").read_text(encoding="utf-8")
    assert "ssh" in script
    assert "tar" in script
    assert 'K8S_DEPLOY_HOST="${K8S_DEPLOY_HOST:-192.168.99.131}"' in script
    assert "deploy/k8s/build-images.sh" in script
    assert "deploy/k8s/deploy.sh" in script
    assert "kubectl -n ai-studio get pods,services,persistentvolumeclaims" in script
    assert "--skip-build" in script
    assert "--exclude=.hf-cache" in script
    assert "docker run --rm --privileged" in script
    assert "node:22-bookworm" in script
    assert "K8S_DEPLOY_REUSE_BACKEND_DEPS" in script


def test_deploy_script_is_local_only_and_does_not_run_remote_git_or_delete_data():
    script = (ROOT / "deploy/k8s/one-click-deploy.sh").read_text(encoding="utf-8")
    assert "git push" not in script
    assert "git commit" not in script
    assert "down -v" not in script
    assert "docker volume rm" not in script
    assert "docker compose" not in script
    assert "require_command ctr" not in script
    assert "command -v ctr" not in script
    assert "chroot /host ctr" not in script


def test_up_works_without_an_explicit_ssh_key(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_ssh = fake_bin / "ssh"
    fake_ssh.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"$*\" == *mktemp* ]]; then\n"
        "  printf '%s\\n' /tmp/ai-studio-k8s-deploy.test\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_ssh.chmod(0o755)
    fake_tar = fake_bin / "tar"
    fake_tar.write_text("#!/usr/bin/env bash\ncat >/dev/null\n", encoding="utf-8")
    fake_tar.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["K8S_DEPLOY_HOST"] = "test-server"
    env["K8S_DEPLOY_USER"] = "test-user"
    env.pop("K8S_DEPLOY_SSH_KEY", None)

    result = subprocess.run(
        [str(ROOT / "deploy/k8s/one-click-deploy.sh"), "up"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_readme_points_kubernetes_users_to_the_script():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "./deploy/k8s/one-click-deploy.sh" in readme
    assert "Kubernetes" in readme
