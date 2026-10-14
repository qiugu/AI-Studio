from pathlib import Path

import yaml


PROJECT_ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "deploy/k8s/configmap.yaml").exists()
)


def test_k8s_sentence_transformers_runs_offline():
    """离线集群必须直接读持久化模型缓存，不能先等待 Hub DNS 超时。"""
    documents = list(
        yaml.safe_load_all(
            (PROJECT_ROOT / "deploy/k8s/configmap.yaml").read_text(encoding="utf-8")
        )
    )
    config_map = next(
        doc
        for doc in documents
        if doc.get("kind") == "ConfigMap"
        and doc.get("metadata", {}).get("name") == "ai-studio-config"
    )

    assert config_map["data"]["HF_HUB_OFFLINE"] == "1"
    assert config_map["data"]["TRANSFORMERS_OFFLINE"] == "1"
