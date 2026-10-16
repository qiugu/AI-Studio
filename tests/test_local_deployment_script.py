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


def test_readme_points_kubernetes_users_to_the_script():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "./deploy/k8s/one-click-deploy.sh" in readme
    assert "Kubernetes" in readme
