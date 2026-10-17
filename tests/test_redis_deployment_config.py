from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_compose_redis_uses_secret_backed_password_and_memory_policy():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "REDIS_PASSWORD: ${REDIS_PASSWORD:-}" in compose
    assert "maxmemory-policy" in compose
    assert "noeviction" in compose


def test_kubernetes_redis_uses_secret_password_and_memory_policy():
    manifest = (ROOT / "deploy/k8s/datastores.yaml").read_text(encoding="utf-8")

    assert "key: REDIS_PASSWORD" in manifest
    assert "maxmemory-policy" in manifest
    assert "redis-cli --no-auth-warning -a \"$REDIS_PASSWORD\"" in manifest


def test_kubernetes_deploy_generates_and_preserves_redis_password():
    script = (ROOT / "deploy/k8s/deploy.sh").read_text(encoding="utf-8")

    assert 'redis_password="$(openssl rand -hex 32)"' in script
    assert 'patch_secret_key_if_missing "REDIS_PASSWORD"' in script
