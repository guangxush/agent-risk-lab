"""
核心数据模型单元测试
"""

from datetime import datetime

import pytest

from agent_risk_lab.core.models import (
    Conversation,
    Message,
    RiskEvent,
    RiskSeverity,
    RiskType,
    RuleViolation,
)


class TestRiskEvent:
    """RiskEvent 模型测试"""

    def test_创建风险事件(self):
        event = RiskEvent(
            conversation_id="conv-001",
            risk_type=RiskType.HALLUCINATION,
            severity=RiskSeverity.HIGH,
            confidence=0.92,
            evidence="模型声称北京是上海的首都，存在明显事实错误",
        )
        assert event.conversation_id == "conv-001"
        assert event.severity == RiskSeverity.HIGH
        assert event.confidence == 0.92

    def test_is_high_risk_高风险(self):
        event = RiskEvent(
            conversation_id="conv-001",
            risk_type=RiskType.HALLUCINATION,
            severity=RiskSeverity.HIGH,
            confidence=0.9,
            evidence="...",
        )
        assert event.is_high_risk() is True

    def test_is_high_risk_极高风险(self):
        event = RiskEvent(
            conversation_id="conv-001",
            risk_type=RiskType.HARMFUL_CONTENT,
            severity=RiskSeverity.CRITICAL,
            confidence=0.99,
            evidence="...",
        )
        assert event.is_high_risk() is True

    def test_is_high_risk_低风险(self):
        event = RiskEvent(
            conversation_id="conv-001",
            risk_type=RiskType.OFF_TOPIC,
            severity=RiskSeverity.LOW,
            confidence=0.6,
            evidence="...",
        )
        assert event.is_high_risk() is False

    def test_置信度范围校验(self):
        with pytest.raises(Exception):
            RiskEvent(
                conversation_id="conv-001",
                risk_type=RiskType.HALLUCINATION,
                severity=RiskSeverity.LOW,
                confidence=1.5,  # 超出 0~1 范围，应触发校验失败
                evidence="...",
            )

    def test_自动填充时间戳(self):
        event = RiskEvent(
            conversation_id="conv-001",
            risk_type=RiskType.HALLUCINATION,
            severity=RiskSeverity.MEDIUM,
            confidence=0.8,
            evidence="...",
        )
        assert isinstance(event.timestamp, datetime)


class TestConversation:
    """Conversation 模型测试"""

    def test_创建对话记录(self):
        conv = Conversation(
            conversation_id="conv-001",
            messages=[
                Message(role="user", content="你好"),
                Message(role="assistant", content="你好，有什么可以帮您的？"),
            ],
        )
        assert len(conv.messages) == 2
        assert conv.messages[0].role == "user"

    def test_实验组标签(self):
        conv = Conversation(
            conversation_id="conv-001",
            messages=[Message(role="user", content="test")],
            experiment_id="exp-001",
            experiment_group="treatment",
        )
        assert conv.experiment_group == "treatment"
        assert conv.experiment_id == "exp-001"
