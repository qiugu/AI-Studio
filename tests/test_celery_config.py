from app.core.config import Config


def test_celery_broker_url_is_built_from_rabbitmq_settings():
    config = Config(
        celery_broker_url="",
        rabbitmq_host="rabbitmq",
        rabbitmq_port=5672,
        rabbitmq_username="worker@example.com",
        rabbitmq_password="p@ss/word",
        rabbitmq_vhost="ai-studio",
    )

    assert config.get_celery_broker_url() == (
        "amqp://worker%40example.com:p%40ss%2Fword@rabbitmq:5672/ai-studio"
    )


def test_explicit_celery_broker_url_takes_precedence():
    config = Config(
        celery_broker_url="amqps://managed.example/vhost",
        rabbitmq_host="rabbitmq",
        rabbitmq_password="ignored",
    )

    assert config.get_celery_broker_url() == "amqps://managed.example/vhost"


def test_celery_result_backend_is_disabled_by_default():
    assert Config(celery_result_backend="").get_celery_result_backend() is None


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
