"""YAML task configuration loader.

Loads task YAML files from the package data directory or arbitrary paths,
parses them with PyYAML, and validates them with the TaskConfig Pydantic model.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml

from ai_resource_eval.api.types import TaskConfig

logger = logging.getLogger(__name__)

# Directory containing bundled YAML task configs (sibling to this module).
_TASKS_DIR = Path(__file__).parent

# install_popularity 默认权重 0：信号采集到 health 输出但不参与 final_score 加权。
# 通过环境变量 HEALTH_W_INSTALL_POPULARITY 可覆盖（合法范围 [0, 1]）。
_INSTALL_POPULARITY_ENV = "HEALTH_W_INSTALL_POPULARITY"
_INSTALL_POPULARITY_DEFAULT_WEIGHT = 0.0


def _resolve_install_popularity_weight() -> float:
    """读取 HEALTH_W_INSTALL_POPULARITY，返回 [0, 1] 之间的权重。

    解析失败或越界则回退到默认值 0.0 并 WARN。
    """
    raw = os.environ.get(_INSTALL_POPULARITY_ENV)
    if raw is None or raw == "":
        return _INSTALL_POPULARITY_DEFAULT_WEIGHT
    try:
        w = float(raw)
    except ValueError:
        logger.warning(
            "%s=%r 不是合法浮点数，回退默认权重 %.2f",
            _INSTALL_POPULARITY_ENV,
            raw,
            _INSTALL_POPULARITY_DEFAULT_WEIGHT,
        )
        return _INSTALL_POPULARITY_DEFAULT_WEIGHT
    if w < 0 or w > 1:
        logger.warning(
            "%s=%s 越界 [0,1]，回退默认权重 %.2f",
            _INSTALL_POPULARITY_ENV,
            w,
            _INSTALL_POPULARITY_DEFAULT_WEIGHT,
        )
        return _INSTALL_POPULARITY_DEFAULT_WEIGHT
    return w


def _inject_install_popularity_signal(raw: dict) -> dict:
    """在解析 TaskConfig 之前，按需注入 install_popularity 信号到 heuristic_signals。

    设计意图：
    - 默认权重 0 时仍要让信号出现在 heuristic_signals 列表里，以便 ScoringGovernor
      与 runner 流程接入；权重 0 不参与现有归一约束（types.py 已跳过）
    - 非零权重则按比例缩减其它信号权重以保证非零信号和 = 1.0
    - 仅对已有 heuristic_signals 的 task config 注入；列表为空说明该 task 不走 health
      混合分支，无需注入
    """
    signals = raw.get("heuristic_signals")
    if not signals:
        return raw

    # 已显式声明则尊重 yaml 配置（用户自定义优先级最高）
    if any(s.get("signal") == "install_popularity" for s in signals):
        return raw

    weight = _resolve_install_popularity_weight()

    # 非零权重：按比例缩减原有信号权重，使「非零信号权重和」仍为 1.0
    if weight > 0:
        existing_sum = sum(float(s.get("weight", 0)) for s in signals)
        if existing_sum > 0:
            scale = (1.0 - weight) / existing_sum
            for s in signals:
                s["weight"] = float(s["weight"]) * scale

    signals.append({"signal": "install_popularity", "weight": weight})
    raw["heuristic_signals"] = signals
    return raw


def load_task_config(task_name: str) -> TaskConfig:
    """Load a built-in task configuration by name.

    Parameters
    ----------
    task_name:
        Task name matching a YAML file in the tasks directory
        (e.g. ``"skill"`` loads ``tasks/skill.yaml``).

    Returns
    -------
    TaskConfig
        Validated task configuration.

    Raises
    ------
    FileNotFoundError
        If no YAML file exists for the given task name.
    ValueError
        If the YAML content fails Pydantic validation.
    """
    path = _TASKS_DIR / f"{task_name}.yaml"
    if not path.exists():
        available = [p.stem for p in _TASKS_DIR.glob("*.yaml")]
        raise FileNotFoundError(
            f"No task config found for {task_name!r}. "
            f"Available tasks: {available}"
        )
    return load_task_config_from_path(path)


def load_task_config_from_path(path: str | Path) -> TaskConfig:
    """Load a task configuration from an arbitrary file path.

    Parameters
    ----------
    path:
        Path to a YAML task configuration file.

    Returns
    -------
    TaskConfig
        Validated task configuration.

    Raises
    ------
    FileNotFoundError
        If the path does not exist.
    ValueError
        If the YAML content fails Pydantic validation.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Task config file not found: {path}")

    with open(path) as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ValueError(f"Expected a YAML mapping, got {type(raw).__name__}")

    # 注入 install_popularity 信号（默认权重 0；env var 可覆盖）
    raw = _inject_install_popularity_signal(raw)

    return TaskConfig(**raw)


def list_available_tasks() -> list[str]:
    """Return names of all built-in task configurations.

    Returns
    -------
    list[str]
        Sorted list of task names (without ``.yaml`` extension).
    """
    return sorted(p.stem for p in _TASKS_DIR.glob("*.yaml"))
