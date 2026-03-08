"""
存储适配器

定义 BaseStorageAdapter 抽象接口，并提供两个内置实现：
- InMemoryAdapter：内存存储，适用于测试和演示场景
- SQLiteAdapter：本地 SQLite 持久化，适用于小团队使用

用户可继承 BaseStorageAdapter 实现自定义后端（MySQL、PostgreSQL、MongoDB 等）。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

from agent_risk_lab.core.models import Conversation, RiskEvent


class BaseStorageAdapter(ABC):
    """存储适配器抽象基类，用户可继承实现自定义存储后端"""

    @abstractmethod
    def save_event(self, event: RiskEvent) -> None:
        """保存风险事件"""
        ...

    @abstractmethod
    def query_events(self, filters: dict[str, Any] | None = None) -> list[RiskEvent]:
        """查询风险事件，支持按字段过滤"""
        ...

    @abstractmethod
    def save_conversation(self, conversation: Conversation) -> None:
        """保存对话记录"""
        ...

    @abstractmethod
    def query_conversations(
        self, filters: dict[str, Any] | None = None
    ) -> list[Conversation]:
        """查询对话记录，支持按字段过滤"""
        ...

    def save_events_batch(self, events: list[RiskEvent]) -> None:
        """批量保存风险事件（默认实现：逐条调用 save_event）"""
        for event in events:
            self.save_event(event)


class InMemoryAdapter(BaseStorageAdapter):
    """
    内存存储适配器

    所有数据存储在内存中，进程退出后数据丢失。
    线程安全，适用于测试、演示和单进程场景。
    """

    def __init__(self) -> None:
        self._events: list[RiskEvent] = []
        self._conversations: list[Conversation] = []
        self._lock = threading.Lock()

    def save_event(self, event: RiskEvent) -> None:
        """线程安全地保存风险事件到内存"""
        with self._lock:
            self._events.append(event)

    def query_events(self, filters: dict[str, Any] | None = None) -> list[RiskEvent]:
        """
        查询风险事件

        支持的过滤字段：
        - conversation_id: 对话 ID
        - risk_type: 风险类型
        - severity: 严重程度
        - experiment_id: 实验 ID
        - experiment_group: 实验分组
        - since: 开始时间（datetime）
        - until: 截止时间（datetime）
        """
        with self._lock:
            results = list(self._events)

        if not filters:
            return results

        return [e for e in results if _match_event(e, filters)]

    def save_conversation(self, conversation: Conversation) -> None:
        """线程安全地保存对话记录到内存"""
        with self._lock:
            self._conversations.append(conversation)

    def query_conversations(
        self, filters: dict[str, Any] | None = None
    ) -> list[Conversation]:
        """查询对话记录，支持按 conversation_id、user_id、experiment_id 过滤"""
        with self._lock:
            results = list(self._conversations)

        if not filters:
            return results

        return [c for c in results if _match_conversation(c, filters)]

    def clear(self) -> None:
        """清空所有数据（用于测试重置）"""
        with self._lock:
            self._events.clear()
            self._conversations.clear()

    def event_count(self) -> int:
        """返回已存储的风险事件数量"""
        with self._lock:
            return len(self._events)


class SQLiteAdapter(BaseStorageAdapter):
    """
    SQLite 本地持久化适配器

    将风险事件和对话记录持久化到本地 SQLite 文件，适用于小团队使用。
    线程安全，自动创建表结构。
    """

    def __init__(self, db_path: str | Path = "agent_risk_lab.db") -> None:
        self._db_path = str(db_path)
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """获取当前线程的数据库连接（每个线程独立连接）"""
        if not hasattr(self._local, "conn"):
            self._local.conn = sqlite3.connect(self._db_path)
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def _init_db(self) -> None:
        """初始化数据库表结构"""
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS risk_events (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT    NOT NULL,
                risk_type       TEXT    NOT NULL,
                severity        TEXT    NOT NULL,
                confidence      REAL    NOT NULL,
                evidence        TEXT    NOT NULL,
                timestamp       TEXT    NOT NULL,
                judge_model     TEXT,
                experiment_id   TEXT,
                experiment_group TEXT,
                metadata        TEXT    DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS conversations (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT    NOT NULL UNIQUE,
                messages        TEXT    NOT NULL,
                user_id         TEXT,
                session_id      TEXT,
                model           TEXT,
                experiment_id   TEXT,
                experiment_group TEXT,
                timestamp       TEXT    NOT NULL,
                metadata        TEXT    DEFAULT '{}'
            );

            CREATE INDEX IF NOT EXISTS idx_events_conv_id
                ON risk_events(conversation_id);
            CREATE INDEX IF NOT EXISTS idx_events_exp_id
                ON risk_events(experiment_id);
            CREATE INDEX IF NOT EXISTS idx_events_risk_type
                ON risk_events(risk_type);
        """)
        conn.commit()

    def save_event(self, event: RiskEvent) -> None:
        """将风险事件持久化到 SQLite"""
        conn = self._get_conn()
        conn.execute(
            """
            INSERT INTO risk_events
                (conversation_id, risk_type, severity, confidence, evidence,
                 timestamp, judge_model, experiment_id, experiment_group, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.conversation_id,
                event.risk_type,
                event.severity.value,
                event.confidence,
                event.evidence,
                event.timestamp.isoformat(),
                event.judge_model,
                event.experiment_id,
                event.experiment_group,
                json.dumps(event.metadata, ensure_ascii=False),
            ),
        )
        conn.commit()

    def query_events(self, filters: dict[str, Any] | None = None) -> list[RiskEvent]:
        """从 SQLite 查询风险事件"""
        conn = self._get_conn()
        sql = "SELECT * FROM risk_events WHERE 1=1"
        params: list[Any] = []

        if filters:
            if "conversation_id" in filters:
                sql += " AND conversation_id = ?"
                params.append(filters["conversation_id"])
            if "risk_type" in filters:
                sql += " AND risk_type = ?"
                params.append(filters["risk_type"])
            if "severity" in filters:
                sql += " AND severity = ?"
                params.append(filters["severity"])
            if "experiment_id" in filters:
                sql += " AND experiment_id = ?"
                params.append(filters["experiment_id"])
            if "experiment_group" in filters:
                sql += " AND experiment_group = ?"
                params.append(filters["experiment_group"])
            if "since" in filters:
                sql += " AND timestamp >= ?"
                params.append(filters["since"].isoformat())
            if "until" in filters:
                sql += " AND timestamp <= ?"
                params.append(filters["until"].isoformat())

        sql += " ORDER BY timestamp DESC"
        rows = conn.execute(sql, params).fetchall()
        return [_row_to_event(row) for row in rows]

    def save_conversation(self, conversation: Conversation) -> None:
        """将对话记录持久化到 SQLite（同一 conversation_id 存在则替换）"""
        conn = self._get_conn()
        conn.execute(
            """
            INSERT OR REPLACE INTO conversations
                (conversation_id, messages, user_id, session_id, model,
                 experiment_id, experiment_group, timestamp, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                conversation.conversation_id,
                conversation.model_dump_json(include={"messages"}),
                conversation.user_id,
                conversation.session_id,
                conversation.model,
                conversation.experiment_id,
                conversation.experiment_group,
                conversation.timestamp.isoformat(),
                json.dumps(conversation.metadata, ensure_ascii=False),
            ),
        )
        conn.commit()

    def query_conversations(
        self, filters: dict[str, Any] | None = None
    ) -> list[Conversation]:
        """从 SQLite 查询对话记录"""
        conn = self._get_conn()
        sql = "SELECT * FROM conversations WHERE 1=1"
        params: list[Any] = []

        if filters:
            if "conversation_id" in filters:
                sql += " AND conversation_id = ?"
                params.append(filters["conversation_id"])
            if "user_id" in filters:
                sql += " AND user_id = ?"
                params.append(filters["user_id"])
            if "experiment_id" in filters:
                sql += " AND experiment_id = ?"
                params.append(filters["experiment_id"])

        sql += " ORDER BY timestamp DESC"
        rows = conn.execute(sql, params).fetchall()
        return [_row_to_conversation(row) for row in rows]


# ── 内部辅助函数 ──────────────────────────────────────────────────────────────

def _match_event(event: RiskEvent, filters: dict[str, Any]) -> bool:
    """判断风险事件是否匹配过滤条件"""
    if "conversation_id" in filters and event.conversation_id != filters["conversation_id"]:
        return False
    if "risk_type" in filters and event.risk_type != filters["risk_type"]:
        return False
    if "severity" in filters and event.severity.value != filters["severity"]:
        return False
    if "experiment_id" in filters and event.experiment_id != filters["experiment_id"]:
        return False
    if "experiment_group" in filters and event.experiment_group != filters["experiment_group"]:
        return False
    if "since" in filters and event.timestamp < filters["since"]:
        return False
    if "until" in filters and event.timestamp > filters["until"]:
        return False
    return True


def _match_conversation(conv: Conversation, filters: dict[str, Any]) -> bool:
    """判断对话记录是否匹配过滤条件"""
    if "conversation_id" in filters and conv.conversation_id != filters["conversation_id"]:
        return False
    if "user_id" in filters and conv.user_id != filters["user_id"]:
        return False
    if "experiment_id" in filters and conv.experiment_id != filters["experiment_id"]:
        return False
    return True


def _row_to_event(row: sqlite3.Row) -> RiskEvent:
    """将 SQLite 行记录转换为 RiskEvent 对象"""
    from agent_risk_lab.core.models import RiskSeverity
    return RiskEvent(
        conversation_id=row["conversation_id"],
        risk_type=row["risk_type"],
        severity=RiskSeverity(row["severity"]),
        confidence=row["confidence"],
        evidence=row["evidence"],
        timestamp=datetime.fromisoformat(row["timestamp"]),
        judge_model=row["judge_model"],
        experiment_id=row["experiment_id"],
        experiment_group=row["experiment_group"],
        metadata=json.loads(row["metadata"] or "{}"),
    )


def _row_to_conversation(row: sqlite3.Row) -> Conversation:
    """将 SQLite 行记录转换为 Conversation 对象"""
    messages_data = json.loads(row["messages"])
    from agent_risk_lab.core.models import Message
    return Conversation(
        conversation_id=row["conversation_id"],
        messages=[Message(**m) for m in messages_data.get("messages", [])],
        user_id=row["user_id"],
        session_id=row["session_id"],
        model=row["model"],
        experiment_id=row["experiment_id"],
        experiment_group=row["experiment_group"],
        timestamp=datetime.fromisoformat(row["timestamp"]),
        metadata=json.loads(row["metadata"] or "{}"),
    )
