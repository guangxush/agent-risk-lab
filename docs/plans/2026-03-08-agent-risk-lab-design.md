# agent-risk-lab 设计文档

**日期：** 2026-03-08
**状态：** 已审批
**协议：** Apache 2.0

---

## 1. 项目背景与目标

`agent-risk-lab` 是一个开源 Python 库，专注于 LLM 应用的在线风险识别与安全评估。目标用户为 AI 应用团队，通过 `pip install agent-risk-lab` 开箱即用。

**核心能力：**
1. **LLM Judge**：采集在线对话日志，识别风险和幻觉
2. **AB 实验风险分析**：在业务变更过程中对比两个版本的 LLM 风险，支持风险识别、诊断、归因
3. **评测集回归验证**：固定评测集定期回归，支持用户自定义风险规则和降噪规则

---

## 2. 整体架构

### 2.1 交付形式

**Python 单包 + extras（方案 C）**：

```bash
pip install agent-risk-lab            # 核心 + CLI
pip install agent-risk-lab[judge]     # + 日志采集依赖（OTEL、SLS）
pip install agent-risk-lab[experiment] # + 统计分析依赖（scipy、pandas）
pip install agent-risk-lab[eval]      # + 报告依赖（jinja2）
pip install agent-risk-lab[all]       # 全部功能
```

### 2.2 目录结构

```
agent-risk-lab/
├── agent_risk_lab/
│   ├── __init__.py
│   ├── core/
│   │   ├── llm_client.py       # 多引擎 LLM 客户端（Claude / GPT-4o / Qwen / Ollama）
│   │   ├── rule_engine.py      # 规则引擎（YAML + Python 插件双层）
│   │   ├── storage.py          # 存储适配器抽象接口
│   │   └── models.py           # 公共数据模型（RiskEvent、RuleViolation 等）
│   ├── judge/
│   │   ├── collectors/
│   │   │   ├── base.py         # BaseCollector 接口
│   │   │   ├── sdk.py          # SDKCollector：Python SDK 直接上报
│   │   │   ├── otel.py         # OTELCollector：OpenTelemetry 集成
│   │   │   ├── webhook.py      # WebhookCollector：HTTP 回调接收
│   │   │   └── sls.py          # SLSCollector：阿里云 SLS 消息管道订阅
│   │   ├── analyzer.py         # Judge 核心：Prompt 构建 → LLM 调用 → 结构化解析
│   │   └── dimensions.py       # 内置风险维度定义（幻觉、有害内容、提示注入等）
│   ├── experiment/
│   │   ├── models.py           # Experiment、ExperimentResult、Attribution 数据模型
│   │   ├── analyzer.py         # AB 对比分析（显著性检验、归因报告）
│   │   └── scheduler.py        # 实验组标签关联逻辑
│   ├── eval/
│   │   ├── dataset.py          # EvalDataset：评测集加载与管理
│   │   ├── runner.py           # EvalRun：回归执行器
│   │   ├── reporter.py         # 报告生成（JSON / HTML）
│   │   └── scheduler.py        # 定时触发（可选依赖）
│   └── cli/
│       ├── __init__.py
│       ├── judge.py            # arl judge 子命令
│       ├── eval.py             # arl eval 子命令
│       └── experiment.py       # arl experiment 子命令
├── rules/
│   ├── default_risks.yaml      # 内置风险规则示例
│   └── default_filters.yaml    # 内置降噪规则示例
├── examples/
│   ├── quickstart_judge.py
│   ├── quickstart_eval.py
│   └── quickstart_experiment.py
├── tests/
│   ├── test_judge/
│   ├── test_experiment/
│   └── test_eval/
├── docs/
│   └── plans/
├── pyproject.toml
├── LICENSE                     # Apache 2.0
├── CONTRIBUTING.md
├── CHANGELOG.md
└── README.md                   # 英文文档
```

### 2.3 数据流

```
日志来源（SDK / OTEL / Webhook / SLS）
       ↓
  judge/collectors/    →  judge/analyzer（LLM Judge 评判）  →  RiskEvent
       ↓（可关联实验组）
  experiment/          →  AB 对比分析  →  归因报告
       ↓（独立使用）
  eval/runner          →  规则引擎过滤  →  回归报告 + 告警
```

---

## 3. 模块 1：judge/ — LLM Judge

### 3.1 采集器（Collector）

所有采集器实现 `BaseCollector` 接口：

| 采集器 | 触发方式 | 适用场景 |
|--------|---------|---------|
| `SDKCollector` | 代码调用 `await judge.log(conversation)` | 直接集成 |
| `OTELCollector` | OpenTelemetry Span 自动捕获 | 已有监控体系 |
| `WebhookCollector` | LLM 网关 HTTP POST | 实时流式处理 |
| `SLSCollector` | 订阅阿里云 SLS 消息管道 | 阿里云生态 |

### 3.2 Judge 核心流程

```
对话日志
  → Prompt 构建（注入风险维度描述 + 用户自定义规则）
  → LLM 调用（可配置多引擎）
  → 结构化响应解析（JSON mode）
  → RiskEvent 输出
```

### 3.3 内置风险维度（可通过 YAML 扩展）

- `hallucination`：事实性幻觉
- `harmful_content`：有害内容输出
- `prompt_injection`：提示词注入攻击
- `data_leakage`：敏感数据泄露
- `off_topic`：话题偏离预期范围

### 3.4 核心数据模型

```python
@dataclass
class RiskEvent:
    conversation_id: str
    risk_type: str          # 风险维度
    severity: str           # low / medium / high / critical
    confidence: float       # 0.0 ~ 1.0
    evidence: str           # LLM Judge 原始解释
    timestamp: datetime
    experiment_group: str | None  # 关联 AB 实验组（可选）
    metadata: dict          # 业务自定义字段
```

---

## 4. 模块 2：experiment/ — AB 实验风险分析

### 4.1 核心概念

- `Experiment`：实验元数据（名称、control 版本、treatment 版本、时间范围）
- `ExperimentResult`：两组聚合风险指标对比
- `Attribution`：归因分析，识别风险差异的来源维度

### 4.2 分析流程

```
用户注册实验 + 为对话打 group 标签（control / treatment）
      ↓
experiment.analyze(experiment_id)
      ↓
对比 control vs treatment：
  - 各维度风险事件率
  - 统计显著性检验（Fisher's exact test / Chi-squared）
  - 置信区间
  - Top-K 高风险样本
      ↓
归因报告：哪类 prompt 类型 / 风险维度差异最显著
```

### 4.3 存储适配器（插件式）

```python
class BaseStorageAdapter(ABC):
    def save_event(self, event: RiskEvent) -> None: ...
    def query_events(self, filters: dict) -> list[RiskEvent]: ...
    def save_experiment(self, exp: Experiment) -> None: ...
    def query_experiment(self, exp_id: str) -> Experiment: ...
```

内置实现：
- `InMemoryAdapter`：内存存储，开箱即用（测试/演示）
- `SQLiteAdapter`：本地 SQLite，适合小团队持久化

---

## 5. 模块 3：eval/ — 评测集回归验证

### 5.1 规则双层体系

**YAML 层（简单规则）：**
```yaml
# rules/my_risks.yaml
rules:
  - name: 拒绝率过高告警
    type: metric_threshold
    metric: rejection_rate
    threshold: 0.05
    severity: high

noise_filters:
  - name: 过滤测试账号
    type: field_match
    field: user_id
    pattern: "^test_.*"
```

**Python 插件层（复杂规则）：**
```python
from agent_risk_lab.eval import BaseRule, EvalResult, RuleViolation

class BusinessRiskRule(BaseRule):
    """自定义业务风险规则"""
    def evaluate(self, result: EvalResult) -> RuleViolation | None:
        # 自定义逻辑
        ...
```

### 5.2 触发方式

- **CLI 手动：** `arl eval run --dataset eval_set.jsonl --model claude-sonnet-4-6`
- **Python SDK：** `eval_suite.run(dataset, config)`
- **定时任务：** `CronScheduler`（`eval` extras 中可选）
- **告警回调：** 出现退步时触发 webhook 通知

### 5.3 报告输出

- 控制台摘要（通过 / 失败 / 风险数量）
- JSON 格式（机器可读，用于 CI/CD）
- HTML 格式（可视化，用于人工审阅）

---

## 6. core/ — 公共基础设施

### 6.1 多引擎 LLM 客户端

```python
# 统一接口，支持多引擎
llm = LLMClient.from_config({
    "provider": "claude",          # claude / openai / qwen / ollama
    "model": "claude-sonnet-4-6",
    "api_key": "...",
})
```

默认推荐引擎：`claude-sonnet-4-6`（评判质量最强）

### 6.2 规则引擎

- 加载 YAML 规则文件
- 动态注册 Python 插件规则
- 规则优先级和冲突解决
- 支持规则热重载

---

## 7. CLI 设计（`arl` 命令）

```bash
# Judge 模块
arl judge analyze --input logs.jsonl --rules rules.yaml --output report.json
arl judge serve --port 8080          # 启动 Webhook 接收服务

# 评测集回归
arl eval run --dataset dataset.jsonl --model claude-sonnet-4-6
arl eval report --run-id <run_id> --format html

# AB 实验
arl experiment register --name exp_001 --control v1.0 --treatment v2.0
arl experiment compare --exp-id exp_001 --output report.html
arl experiment attribute --exp-id exp_001  # 归因分析
```

---

## 8. 开源规范

### 8.1 协议
Apache 2.0

### 8.2 代码规范
- 所有注释和 docstring 使用**中文**
- README 和对外文档使用**英文**
- 格式化工具：`ruff format`
- Lint 工具：`ruff check`
- 测试框架：`pytest`

### 8.3 依赖管理

**核心依赖（必装）：**
- `anthropic` — Claude SDK
- `openai` — GPT 兼容接口
- `pydantic` — 数据模型验证
- `click` — CLI 框架
- `PyYAML` — 规则文件解析

**可选 extras：**
```toml
[project.optional-dependencies]
judge      = ["opentelemetry-sdk>=1.20", "aliyun-log-python-sdk>=0.7"]
experiment = ["scipy>=1.11", "pandas>=2.0"]
eval       = ["jinja2>=3.1", "schedule>=1.2"]
all        = ["agent-risk-lab[judge,experiment,eval]"]
```

### 8.4 CI/CD（GitHub Actions）
- PR：lint（ruff）+ 单元测试（pytest）
- main 分支合并：集成测试
- Tag 推送：自动发布到 PyPI

---

## 9. 技术选型说明

| 决策 | 选择 | 理由 |
|------|------|------|
| 架构方式 | 单包 + extras | 开箱即用，按需安装，单仓库维护简单 |
| LLM 引擎 | 可配置多引擎 | 用户可自选，默认推荐 Claude |
| 存储层 | 插件式适配器 | 不锁定数据库，用户自定义 |
| 规则格式 | YAML + Python 双层 | 简单用 YAML，复杂逻辑用代码 |
| CLI 框架 | click | 成熟稳定，文档完善 |
| 统计分析 | scipy | 标准库，Fisher/Chi-squared 显著性检验 |
