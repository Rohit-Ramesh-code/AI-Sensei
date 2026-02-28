# Technology Stack

**Project:** Project Sentinel (SNMP Printer Monitoring + LangGraph Multi-Agent + EWS Alerts)
**Researched:** 2026-02-28

## Recommended Stack

### Python Runtime

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Python | 3.12+ | Runtime | 3.12 is mature and well-supported by all dependencies. All key libraries (langgraph, pysnmp, exchangelib) require >=3.10. Avoid 3.14 in production -- too new. |

### SNMP Layer

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| pysnmp | 7.1.22 | SNMP GET queries to Lexmark XC2235 | The only actively maintained pure-Python SNMP library. LeXtudio fork (post-etingof) is production/stable. Pure Python means no C compilation issues on Windows. Supports SNMPv1/v2c/v3 with high-level API (hlapi). |

**Confidence:** HIGH -- verified on PyPI (released Oct 2025, Python 3.10+, production/stable status).

**Why not alternatives:**

| Library | Why Not |
|---------|---------|
| easysnmp | Wraps Net-SNMP C library. Requires system-level Net-SNMP installation. Painful on Windows. Not needed for simple GET operations. |
| puresnmp | Smaller community, fewer maintainers, less documentation. pysnmp 7 covers all use cases. |
| etingof/pysnmp (original) | Unmaintained since 2022. The pysnmp/pysnmp fork (LeXtudio) is the successor. |

### LLM Agent Orchestration

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| langgraph | >=1.0.10 | Multi-agent pipeline orchestration | v1.0 is the first stable release. Graph-based architecture maps directly to the project's pipeline: SNMP -> Monitor -> Analyst -> Policy Guard -> Communicator. Supports the Supervisor pattern natively. |
| langchain-core | (auto-installed) | Base abstractions for LLM calls | Dependency of langgraph. Provides ChatModel, messages, tool abstractions. |
| langchain-anthropic | >=1.3.4 | Claude LLM integration | Official LangChain integration for Anthropic models. Use `ChatAnthropic` as the LLM backing the Analyst agent. |

**Confidence:** HIGH -- LangGraph 1.0 is a major milestone, verified on PyPI (released Feb 27, 2026). langchain-anthropic 1.3.4 released Feb 24, 2026.

**Why not alternatives:**

| Framework | Why Not |
|-----------|---------|
| CrewAI | Higher-level abstraction hides control flow. Project Sentinel needs explicit graph edges (e.g., Policy Guard gating Communicator). LangGraph's StateGraph gives that control. |
| AutoGen | Microsoft's framework focuses on conversational multi-agent. Sentinel's pipeline is sequential with conditional branching, not conversational. |
| Raw Anthropic SDK | No graph orchestration, state management, or agent coordination built in. Would require reimplementing what LangGraph provides. |
| LangChain agents (legacy) | LangChain itself recommends LangGraph for all new agent implementations. Legacy agents are built on LangGraph anyway. |

### Email Transport (EWS)

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| exchangelib | >=5.6.0 | Send alert emails via Microsoft Exchange (EWS) | The standard Python EWS client. Well-maintained (Oct 2025 release), supports Exchange 2007-2016 and Office 365. Handles autodiscover, authentication, and message composition. No viable alternative exists for on-prem Exchange. |

**Confidence:** HIGH -- verified on PyPI. Only serious Python EWS library.

### Configuration Management

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| pydantic-settings | >=2.13.1 | Type-safe configuration from .env and environment variables | Automatic type validation and conversion for all config values (SNMP_HOST, thresholds, etc.). SecretStr support for passwords. Replaces scattered os.getenv() calls with a single validated Settings object. |
| python-dotenv | >=1.0.1 | Load .env files | pydantic-settings uses this under the hood for .env file loading. Install explicitly for clarity. |

**Confidence:** HIGH -- pydantic-settings is the modern standard (Feb 2026 release). CLAUDE.md already references python-dotenv; pydantic-settings builds on it with type safety.

**Why not python-dotenv alone:** No type validation. Every os.getenv() returns Optional[str]. You end up writing manual int(), float(), and None-checks everywhere. pydantic-settings eliminates this entirely.

### Scheduling

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| APScheduler | >=3.11.2 | Scheduled hourly SNMP polling | Interval and cron triggers, job persistence across restarts, production-grade. The project needs reliable hourly polling that survives crashes. |

**Confidence:** HIGH -- verified on PyPI (Dec 2025 release). Mature library (3.x branch is stable; 4.x is alpha, avoid it).

**Why not alternatives:**

| Library | Why Not |
|---------|---------|
| schedule | No persistence, no async support, blocks main thread by default. Fine for scripts, wrong for a long-running monitoring service. |
| celery | Massive overkill. Requires a message broker (Redis/RabbitMQ). Sentinel is a single-process system polling one printer hourly. |
| cron (OS-level) | Ties deployment to OS. Not portable. Harder to integrate with Python state (trend tracking). |

### Logging and Data

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| structlog | >=24.4.0 | Structured logging for agent decisions | JSON-formatted logs with context (printer_id, toner_level, action). Much better than stdlib logging for machine-parseable audit trails. Aligns with printer_history.json requirement. |
| pydantic | >=2.10 (auto-installed) | Data models for agent state | Already a dependency of pydantic-settings and langchain. Use for SNMP data models, alert payloads, and LangGraph state schemas. |

**Confidence:** MEDIUM for structlog (best practice but project could use stdlib logging). HIGH for pydantic (already a transitive dependency).

### Development Tools

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| pytest | >=8.0 | Testing | Standard Python test framework. |
| pytest-asyncio | >=0.24 | Async test support | LangGraph operations are async. Need async test fixtures. |
| ruff | >=0.9.0 | Linting and formatting | Replaces flake8 + black + isort. Single tool, extremely fast. |

**Confidence:** HIGH -- industry standard tools.

## Full Dependency Summary

### Core Dependencies

```bash
pip install langgraph langchain-anthropic pysnmp exchangelib apscheduler pydantic-settings python-dotenv structlog
```

### Dev Dependencies

```bash
pip install pytest pytest-asyncio ruff
```

### requirements.txt

```
langgraph>=1.0.10
langchain-anthropic>=1.3.4
pysnmp>=7.1.22
exchangelib>=5.6.0
apscheduler>=3.11,<4.0
pydantic-settings>=2.13.1
python-dotenv>=1.0.1
structlog>=24.4.0
```

### requirements-dev.txt

```
pytest>=8.0
pytest-asyncio>=0.24
ruff>=0.9.0
```

## Architecture-Stack Mapping

| Project Component | Primary Library | Notes |
|-------------------|----------------|-------|
| `adapters/snmp_adapter.py` | pysnmp 7.1 (hlapi) | Use `get_cmd()` with `CommunityData` for SNMPv2c GET |
| `adapters/ews_scraper.py` | exchangelib | `Account` + `Message` for outbound email |
| `agents/supervisor.py` | langgraph `StateGraph` | Define nodes for Monitor, Analyst, PolicyGuard, Communicator |
| `agents/analyst.py` | langchain-anthropic `ChatAnthropic` | LLM-powered analysis node in the graph |
| `agents/communicator.py` | exchangelib (via ews_scraper) | Sends emails only after Policy Guard clears |
| `guardrails/safety_logic.py` | pydantic (validation) + structlog (audit) | Rate limit logic + confidence threshold checks |
| `main.py` | APScheduler | `IntervalTrigger` for hourly polling |
| Configuration | pydantic-settings | Single `Settings` class loading from `.env` |
| Logging | structlog | JSON output to printer_history.json |

## Critical Version Pins

- **APScheduler**: Pin to `>=3.11,<4.0`. APScheduler 4.x is a ground-up rewrite with breaking API changes and is still alpha. Do not use it.
- **pysnmp**: Pin to `>=7.1`. Versions below 7.0 are the unmaintained etingof fork.
- **langgraph**: Pin to `>=1.0`. Pre-1.0 versions had breaking changes between minor versions.
- **pydantic**: The ecosystem (pydantic-settings, langchain) has fully migrated to Pydantic v2. Do not use Pydantic v1.

## What NOT to Use

| Technology | Why Avoid |
|------------|-----------|
| easysnmp | C dependency (Net-SNMP). Windows compilation pain. Unnecessary for simple GET queries. |
| pysnmp < 7.0 (etingof) | Unmaintained since 2022. Security and compatibility risks. |
| APScheduler 4.x | Alpha quality. Breaking API changes from 3.x. Not production-ready. |
| Celery | Requires message broker infrastructure. Massive overkill for hourly polling of one printer. |
| schedule | No persistence, no async, blocks main thread. Not suitable for a long-running service. |
| CrewAI / AutoGen | Less control over graph edges and state flow than LangGraph. Project needs explicit pipeline control. |
| Flask / FastAPI | No web UI in v1 scope. Adding a web framework adds complexity with zero value. |
| Pydantic v1 | Entire ecosystem has moved to v2. Mixing versions causes conflicts. |

## Sources

- [LangGraph PyPI](https://pypi.org/project/langgraph/) -- v1.0.10, released Feb 27, 2026
- [LangGraph 1.0 Announcement](https://blog.langchain.com/langchain-langgraph-1dot0/)
- [langchain-anthropic PyPI](https://pypi.org/project/langchain-anthropic/) -- v1.3.4, released Feb 24, 2026
- [pysnmp PyPI](https://pypi.org/project/pysnmp/) -- v7.1.22, released Oct 26, 2025
- [PySNMP 7.1 Documentation](https://docs.lextudio.com/pysnmp/v7.1/index.html)
- [exchangelib PyPI](https://pypi.org/project/exchangelib/) -- v5.6.0, released Oct 10, 2025
- [exchangelib GitHub](https://github.com/ecederstrand/exchangelib)
- [APScheduler PyPI](https://pypi.org/project/APScheduler/) -- v3.11.2, released Dec 22, 2025
- [pydantic-settings PyPI](https://pypi.org/project/pydantic-settings/) -- v2.13.1, released Feb 19, 2026
- [Pydantic Settings Docs](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
- [LangGraph Overview](https://docs.langchain.com/oss/python/langgraph/overview)
