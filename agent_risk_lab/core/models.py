"""
公共数据模型

定义贯穿三个模块（judge、experiment、eval）的核心数据结构。
所有模型基于 Pydantic v2，支持序列化和类型验证。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class RiskSeverity(str, Enum):
    """风险严重程度等级"""

    LOW = "low"           # 低风险：轻微偏差，不影响核心功能
    MEDIUM = "medium"     # 中风险：明显问题，可能影响用户体验
    HIGH = "high"         # 高风险：严重偏差，需要人工审核
    CRITICAL = "critical" # 极高风险：可能造成危害，需立即处理


class RiskType(str, Enum):
    """内置风险维度类型（用户可通过 YAML 扩展自定义类型）"""

    HALLUCINATION = "hallucination"         # 事实性幻觉：输出与事实不符
    HARMFUL_CONTENT = "harmful_content"     # 有害内容：违规、歧视、暴力等
    PROMPT_INJECTION = "prompt_injection"   # 提示词注入：用户绕过系统指令
    DATA_LEAKAGE = "data_leakage"           # 数据泄露：敏感信息外泄
    OFF_TOPIC = "off_topic"                 # 话题偏离：回答与业务场景不相关
    CUSTOM = "custom"                       # 自定义风险类型


class Message(BaseModel):
    """单条对话消息"""

    role: str = Field(..., description="消息角色：user / assistant / system")
    content: str = Field(..., description="消息内容")
    timestamp: datetime | None = Field(default=None, description="消息时间戳")
    metadata: dict[str, Any] = Field(default_factory=dict, description="消息附加元数据")


class Conversation(BaseModel):
    """一次完整的对话记录"""

    conversation_id: str = Field(..., description="对话唯一标识")
    messages: list[Message] = Field(..., description="消息列表，按时间顺序排列")
    user_id: str | None = Field(default=None, description="用户标识")
    session_id: str | None = Field(default=None, description="会话标识")
    model: str | None = Field(default=None, description="使用的 LLM 模型名称")
    experiment_group: str | None = Field(
        default=None, description="AB 实验组标签：control / treatment"
    )
    experiment_id: str | None = Field(default=None, description="关联的 AB 实验 ID")
    timestamp: datetime = Field(
        default_factory=datetime.utcnow, description="对话开始时间"
    )
    metadata: dict[str, Any] = Field(default_factory=dict, description="业务自定义字段")


class RiskEvent(BaseModel):
    """风险事件：Judge 模块输出的核心结果"""

    conversation_id: str = Field(..., description="来源对话 ID")
    risk_type: str = Field(..., description="风险类型（内置或自定义）")
    severity: RiskSeverity = Field(..., description="风险严重程度")
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Judge 置信度（0.0 ~ 1.0）"
    )
    evidence: str = Field(..., description="LLM Judge 的原始判断依据和解释")
    timestamp: datetime = Field(
        default_factory=datetime.utcnow, description="风险事件发现时间"
    )
    judge_model: str | None = Field(default=None, description="执行判断的 LLM 模型")
    experiment_group: str | None = Field(
        default=None, description="关联 AB 实验组（若存在）"
    )
    experiment_id: str | None = Field(default=None, description="关联 AB 实验 ID")
    metadata: dict[str, Any] = Field(default_factory=dict, description="附加上下文信息")

    def is_high_risk(self) -> bool:
        """判断是否为高风险或极高风险事件"""
        return self.severity in (RiskSeverity.HIGH, RiskSeverity.CRITICAL)


class RuleViolation(BaseModel):
    """规则违反记录：规则引擎输出的结果"""

    rule_name: str = Field(..., description="触发的规则名称")
    rule_type: str = Field(..., description="规则类型：metric_threshold / field_match / custom")
    severity: RiskSeverity = Field(..., description="规则定义的风险等级")
    message: str = Field(..., description="违规描述信息")
    actual_value: Any = Field(default=None, description="实际检测到的值")
    threshold_value: Any = Field(default=None, description="规则阈值")
    context: dict[str, Any] = Field(default_factory=dict, description="违规上下文")
