from app.core.config import Config


def test_celery_urls_inject_redis_password_when_missing():
    config = Config(
        redis_host="127.0.0.1",
        redis_port=6379,
        redis_db=1,
        redis_password="secret123",
        celery_broker_url="redis://127.0.0.1:6379/1",
        celery_result_backend="redis://127.0.0.1:6379/2",
    )

    assert config.get_celery_broker_url() == "redis://:secret123@127.0.0.1:6379/1"
    assert config.get_celery_result_backend() == "redis://:secret123@127.0.0.1:6379/2"
