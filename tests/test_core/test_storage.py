"""
存储适配器单元测试（InMemoryAdapter 和 SQLiteAdapter）
"""

import tempfile
from pathlib import Path

import pytest

from agent_risk_lab.core.models import (
    Conversation,
    Message,
    RiskEvent,
    RiskSeverity,
    RiskType,
)
from agent_risk_lab.core.storage import InMemoryAdapter, SQLiteAdapter


def _make_event(
    conversation_id: str = "conv-001",
    risk_type: str = RiskType.HALLUCINATION,
    severity: RiskSeverity = RiskSeverity.HIGH,
    experiment_id: str | None = None,
    experiment_group: str | None = None,
) -> RiskEvent:
    """测试辅助：创建风险事件"""
    return RiskEvent(
        conversation_id=conversation_id,
        risk_type=risk_type,
        severity=severity,
        confidence=0.9,
        evidence="测试证据",
        experiment_id=experiment_id,
        experiment_group=experiment_group,
    )


def _make_conversation(conversation_id: str = "conv-001") -> Conversation:
    """测试辅助：创建对话记录"""
    return Conversation(
        conversation_id=conversation_id,
        messages=[Message(role="user", content="测试消息")],
    )


class TestInMemoryAdapter:
    """InMemoryAdapter 测试"""

    def test_保存和查询风险事件(self):
        adapter = InMemoryAdapter()
        event = _make_event()
        adapter.save_event(event)

        results = adapter.query_events()
        assert len(results) == 1
        assert results[0].conversation_id == "conv-001"

    def test_按对话ID过滤(self):
        adapter = InMemoryAdapter()
        adapter.save_event(_make_event("conv-001"))
        adapter.save_event(_make_event("conv-002"))

        results = adapter.query_events({"conversation_id": "conv-001"})
        assert len(results) == 1
        assert results[0].conversation_id == "conv-001"

    def test_按实验组过滤(self):
        adapter = InMemoryAdapter()
        adapter.save_event(_make_event(experiment_id="exp-1", experiment_group="control"))
        adapter.save_event(_make_event(experiment_id="exp-1", experiment_group="treatment"))

        results = adapter.query_events({"experiment_group": "control"})
        assert len(results) == 1

    def test_保存和查询对话记录(self):
        adapter = InMemoryAdapter()
        conv = _make_conversation()
        adapter.save_conversation(conv)

        results = adapter.query_conversations()
        assert len(results) == 1

    def test_清空数据(self):
        adapter = InMemoryAdapter()
        adapter.save_event(_make_event())
        adapter.clear()
        assert adapter.event_count() == 0

    def test_批量保存事件(self):
        adapter = InMemoryAdapter()
        events = [_make_event(f"conv-{i}") for i in range(5)]
        adapter.save_events_batch(events)
        assert adapter.event_count() == 5


class TestSQLiteAdapter:
    """SQLiteAdapter 测试"""

    def test_保存和查询风险事件(self, tmp_path: Path):
        adapter = SQLiteAdapter(tmp_path / "test.db")
        event = _make_event()
        adapter.save_event(event)

        results = adapter.query_events()
        assert len(results) == 1
        assert results[0].conversation_id == "conv-001"
        assert results[0].severity == RiskSeverity.HIGH

    def test_持久化验证(self, tmp_path: Path):
        """验证数据写入后重新连接仍可读取"""
        db_path = tmp_path / "test.db"
        adapter1 = SQLiteAdapter(db_path)
        adapter1.save_event(_make_event())

        # 使用新适配器实例（不同连接）读取
        adapter2 = SQLiteAdapter(db_path)
        results = adapter2.query_events()
        assert len(results) == 1

    def test_按实验ID过滤(self, tmp_path: Path):
        adapter = SQLiteAdapter(tmp_path / "test.db")
        adapter.save_event(_make_event(experiment_id="exp-001"))
        adapter.save_event(_make_event(experiment_id="exp-002"))

        results = adapter.query_events({"experiment_id": "exp-001"})
        assert len(results) == 1

    def test_保存和查询对话记录(self, tmp_path: Path):
        adapter = SQLiteAdapter(tmp_path / "test.db")
        conv = _make_conversation()
        adapter.save_conversation(conv)

        results = adapter.query_conversations()
        assert len(results) == 1
        assert results[0].conversation_id == "conv-001"
        assert len(results[0].messages) == 1
