# Feature Landscape

**Domain:** Printer monitoring and proactive maintenance alerting (SNMP-based, AI-driven)
**Researched:** 2026-02-28
**Confidence:** MEDIUM-HIGH (well-established domain; AI-driven prediction layer is the novel part)

## Table Stakes

Features users expect. Missing = product feels incomplete or no better than checking the printer LCD panel.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **SNMP toner level polling** | The entire system's purpose; every printer monitoring tool does this | Low | Standard OIDs: `1.3.6.1.2.1.43.11.1.1.9` (current level), `1.3.6.1.2.1.43.11.1.1.8` (max capacity). Lexmark has a known quirk: returns `-3` when below low threshold in legacy compat mode -- must handle this |
| **Per-color toner tracking** | The XC2235 is a color printer with CMYK supplies; reporting only "toner %" without per-color breakdown is useless | Low | Walk the supplies table (`1.3.6.1.2.1.43.11.1.1.*`), each row is a different supply (Black, Cyan, Magenta, Yellow) |
| **Threshold-based low toner alerts** | The minimum viable alert -- "toner is below X%" | Low | Configurable threshold (default 20%). Every MPS tool and Nagios plugin does this |
| **Email alert delivery** | The specified delivery channel; admin needs a notification they can act on | Med | EWS via exchangelib. Alert must include: which supply, current %, recommended action |
| **Scheduled polling** | System must run autonomously, not require manual triggering | Low | Hourly cron/scheduler. Standard for the domain (Domotz, OpManager, etc. all poll on intervals) |
| **Alert rate limiting** | Without this, hourly polling = hourly emails = alert fatigue = ignored alerts | Low | 1 alert per printer per 24h is the project's stated design. This is table stakes because MPS providers universally suppress duplicate alerts |
| **Persistent history logging** | Need to know what happened, when alerts fired, what was suppressed | Low | JSON log file per project spec. Enables debugging and audit trail |
| **SNMP data validation** | Stale, null, or out-of-range SNMP values must not trigger false alerts | Med | The Policy Guard's data quality check. Critical because SNMP can return `-1` (unknown), `-2` (unknown), `-3` (Lexmark low-level encoding), or timeout on network issues |
| **Actionable alert content** | Alert emails that say "toner low" without specifics are not actionable | Low | Include: printer name/IP, supply color, current %, recommended action (e.g., "Order Lexmark XC2235 black toner cartridge") |

## Differentiators

Features that set Project Sentinel apart from a simple threshold script or Nagios check. These justify the AI/LLM agent architecture.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Time-to-depletion estimate** | Transforms alert from reactive ("it's low now") to predictive ("you have ~12 days"). Gives procurement lead time | Med | Requires historical trend data. Calculate consumption rate from delta between polls. LLM synthesizes estimate from rate + current level. This is Project Sentinel's core differentiator |
| **LLM confidence scoring** | Self-reported confidence (0.0-1.0) lets the system gate alerts on quality, not just thresholds. Prevents spurious alerts when data is noisy or trend is unclear | Med | Two-layer: LLM self-score + data quality check. Novel compared to simple threshold tools. Confidence below threshold = suppressed alert + logged reason |
| **Trend-aware alerting** | Alert considers consumption velocity, not just absolute level. A printer at 25% with heavy use is more urgent than one at 15% that barely prints | High | Requires sufficient historical data points. LLM Analyst can weigh velocity vs. absolute level. This is where AI adds real value over static thresholds |
| **Natural language alert reasoning** | LLM can explain WHY it is alerting in plain English, not just report numbers. "Black toner at 18%, depleting at ~2% per day based on 14-day trend. Estimated 9 days remaining. Recommend ordering replacement this week." | Med | LLM prompt engineering to produce human-readable analysis. Makes alerts actionable for non-technical procurement staff |
| **Suppression logging with reasons** | When an alert is suppressed (rate limit, low confidence, stale data), log exactly why. Enables trust in the system -- admin can audit that suppression was justified | Low | Already in project spec. Uncommon in simple monitoring tools. Builds trust in the AI layer |
| **Multi-supply depletion correlation** | Alert when multiple supplies are trending low simultaneously -- suggests ordering a full supply kit rather than individual cartridges | Med | LLM can synthesize across supply readings in a single analysis pass. Saves procurement effort |

## Anti-Features

Features to explicitly NOT build in v1. These are complexity traps that the project spec wisely scopes out.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| **Web dashboard / status UI** | Massive scope expansion (frontend framework, hosting, auth, real-time updates). Alert emails are the v1 delivery mechanism and they work | Send well-formatted email alerts. If status visibility is needed later, a simple static HTML report generated alongside the JSON log is a fraction of the effort |
| **Multi-printer fleet management** | Architecture supports it, but fleet UI, per-printer config, fleet-wide analytics, and printer discovery are each large features. Solve for one printer first | Design adapters and agents to accept printer config as parameter. v2 can loop over a printer list without architectural changes |
| **Inbound email command processing** | Parsing inbound emails is fragile (MIME parsing, intent detection, security). Adds bidirectional EWS complexity for marginal v1 value | One-way outbound alerts only. If commands are needed later, a simple config file or API endpoint is more reliable than email parsing |
| **Automatic toner ordering / procurement integration** | Liability risk, requires vendor API integration, approval workflows, payment processing. The human-in-the-loop is a feature, not a limitation | Recommend action in alert email. Human decides and orders. Much safer for v1 |
| **Paper level / jam / door-open monitoring** | Scope creep. These are different SNMP OID trees, different alert logic, different urgency levels. Toner prediction is the core value | Focus on toner/supply consumables. Paper events are real-time (jam happens, you fix it). Toner depletion is predictive -- that is where AI adds value |
| **SNMP auto-discovery** | Network scanning raises security concerns, requires subnet configuration, handles diverse device types. One known printer IP is sufficient for v1 | Hardcode printer IP in `.env`. Fleet discovery is a v2 concern |
| **OAuth / modern auth for Exchange** | Service account credentials work. OAuth adds token refresh, app registration, consent flows -- significant complexity for zero v1 benefit | Use basic auth via service account. Migrate to OAuth if the Exchange server requires it later |
| **Mobile push notifications** | Requires push notification service, mobile app or PWA, device registration. Email already reaches mobile devices | Email alerts are readable on mobile. If urgency requires push, integrate with Teams/Slack webhooks (much simpler than mobile push) |
| **Page count / cost tracking** | Cost-per-page analysis is a different product (print management, not supply monitoring). Different OIDs, different analytics, different audience | Stay focused on supply depletion prediction. Cost tracking is a separate concern |

## Feature Dependencies

```
SNMP toner level polling
  --> Per-color toner tracking (same SNMP walk, just parse all rows)
  --> Persistent history logging (store each poll result)
      --> Time-to-depletion estimate (needs historical data points)
          --> Trend-aware alerting (needs consumption velocity from history)
          --> Multi-supply depletion correlation (needs trends for all supplies)
  --> SNMP data validation (validates raw SNMP responses)
      --> LLM confidence scoring (data quality feeds confidence)

Threshold-based low toner alerts
  --> Alert rate limiting (gates alert delivery)
  --> Actionable alert content (formats the alert)
      --> Email alert delivery (sends the formatted alert)
          --> Suppression logging with reasons (logs when delivery is blocked)

LLM confidence scoring
  --> Natural language alert reasoning (LLM produces both score and explanation)
```

## MVP Recommendation

**Phase 1 -- Monitoring Foundation (table stakes only):**

1. SNMP toner level polling with per-color tracking
2. SNMP data validation (handle Lexmark `-3` quirk and error cases)
3. Persistent history logging (every poll stored)
4. Threshold-based alert with actionable content
5. Alert rate limiting (1/day/printer)
6. Email delivery via EWS

This phase delivers a working system that is already more useful than manually checking the printer. No LLM required yet.

**Phase 2 -- AI-Driven Prediction (differentiators):**

7. Time-to-depletion estimate from historical trend data
8. LLM Analyst with confidence scoring
9. Natural language alert reasoning
10. Suppression logging with reasons
11. Trend-aware alerting (velocity-weighted urgency)

This phase is where the AI agent architecture justifies itself. Requires sufficient historical data from Phase 1 polling.

**Defer to v2:**
- Multi-supply depletion correlation: Needs Phase 2 working well first
- Fleet management: Architectural support is free, UI/config is not
- Web dashboard: Only if email alerts prove insufficient

## Sources

- [ManageEngine OpManager - Printer Monitoring](https://www.manageengine.com/network-monitoring/printer-monitoring.html) -- feature set of a mature enterprise monitoring tool
- [Site24x7 Printer Monitoring](https://www.site24x7.com/printer-monitoring.html) -- real-time monitoring capabilities and alert types
- [Domotz Printer Monitoring](https://www.domotz.com/features/printer-monitoring.php) -- intelligent alerts and threshold configuration
- [Nagios SNMP Printer Check Plugin](https://exchange.nagios.org/directory/plugins/hardware/printers/snmp-printer-check/details/) -- baseline SNMP monitoring feature set
- [Claudia Kuenzler - Monitoring Brother Printer with SNMP](https://www.claudiokuenzler.com/blog/1422/monitoring-brother-printer-snmp-alert-low-toner) -- practical SNMP toner monitoring implementation
- [Lexmark SNMP MIBs and OID Values](https://support.lexmark.com/en_us/printers/printer/E462/article/FA615.html) -- Lexmark-specific SNMP behavior including `-3` low-level encoding
- [alfonsrv/printer-monitoring on GitHub](https://github.com/alfonsrv/printer-monitoring) -- open-source Python SNMP printer monitoring reference implementation
- [Carden Managed Print - Predictive Toner Management](https://cardenmanagedprint.co.uk/how-predictive-toner-management-prevents-printer-downtime/) -- predictive toner management in MPS context
- [SumnerOne - AI-Driven Predictive Maintenance for Printing](https://www.sumnerone.com/blog/ai-driven-predictive-maintenance) -- AI/ML applied to printer maintenance prediction
- [EventSentry - Monitor Printer Toner Levels](https://www.eventsentry.com/kb/430-how-do-i-monitor-the-toner-level-of-a-printer-or-mfd-device) -- SNMP OID reference for toner monitoring
