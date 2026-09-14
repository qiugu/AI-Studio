"""pytest 全局引导。

必须在导入任何 ``app.*`` 模块之前完成环境准备——``app.core.config`` 在模块导入时
即实例化 ``Config()``，因此本文件顶层的环境变量设置是唯一可靠的注入点。

两项职责：

1. **跳过 ``backend/.env`` 读取**。测试不应依赖本机凭据文件；否则在没有 ``.env``
   的环境（CI、新 clone）中，整个测试套件会在 collection 阶段就因读文件失败而中断。
2. **固定与被测逻辑相关的外部依赖地址**，避免测试结果受开发者本机环境变量影响。
3. **禁止 HuggingFace 联网探测**。测试只应使用本地缓存权重。
"""

import os

os.environ.setdefault("AI_STUDIO_SKIP_ENV_FILE", "1")

# HuggingFace 一律离线：模型 id 解析必须只查本地缓存。
# 若不禁用，缓存命中的模型 id 也会先发 HEAD 请求做版本探测；在「外网经代理、而
# 代理对该请求无响应」的开发环境下，该请求不是快速失败而是**长时间挂起**——实测
# 整套测试会卡在第一个加载真实模型的用例上超过 17 分钟无任何输出。
# 离线后行为变为确定性的：缓存命中则加载，未命中则立即报错，绝不静默悬挂。
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

# 外部服务地址：仅在开发者未显式指定时兜底。真连不上的用例应自行 skip，
# 而不是让整套测试报错。
os.environ.setdefault("QDRANT_URL", "http://127.0.0.1:6333")

# 本机 127.0.0.1 / localhost 的探测一律绕过 HTTP 代理。
# 开发机常为访问外网配置全局代理，若不排除本地地址，集成用例会经由代理访问
# 本地 Qdrant 并收到 502，最终表现为「服务不可达」的误判。
_existing_no_proxy = os.environ.get("NO_PROXY", "")
for _host in ("127.0.0.1", "localhost"):
    if _host not in _existing_no_proxy:
        _existing_no_proxy = f"{_existing_no_proxy},{_host}" if _existing_no_proxy else _host
for _key in ("NO_PROXY", "no_proxy"):
    os.environ[_key] = _existing_no_proxy
