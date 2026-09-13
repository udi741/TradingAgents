# TradingAgents + authenticated Devin CLI: minimal-change implementation guide

**Prepared:** 2026-09-12  
**Status:** Implementation specification, not an implemented or locally tested bridge.  
**Audience:** The coding agent implementing this integration, and the user relaying its reports for review.

## 1. Read this first

The user's requirement is provider substitution, not an agent-system rewrite:

> Keep the existing TradingAgents application, particularly its Python CLI, graph, agents, prompts, tools, state, and reports. Replace direct LLM-provider access with the user's already-authorized, authenticated Devin CLI.

Assume the account is entitled to use Devin CLI. Verify that the actual execution environment has the executable and can access its normal authenticated session. Do not reopen subscription eligibility research unless an actual runtime error makes it necessary.

This guide **supersedes the architecture in `TradingAgents_Devin_CLI_Implementation_Plan.md`** that proposed replacing individual nodes and migrating financial tools into MCP. Do not combine the two architectures. Previously implemented work must be inspected and reported, not deleted automatically.

### Required outcome

```text
Existing TradingAgents Python CLI
    -> existing LangGraph workflow and agents
    -> existing model interface
    -> ONE compatibility layer
    -> authenticated Devin CLI

Financial tool requests return to TradingAgents.
TradingAgents executes its existing Python tools.
Their results return through the same model interface.
```

The user must not need to supply a paid OpenAI, Anthropic, or other direct LLM-provider API key for the Devin-backed path. Normal Devin authentication is still required. Independent market-data services may still need their own credentials; this integration must not disguise that distinction.

The application should behave the same structurally, not produce byte-identical investment opinions. Different model/runtime instructions can change responses. Do not claim complete behavioral equivalence from a few successful tests.

### Explicit non-goals

- No replacement frontend, generic multi-agent framework, or per-role Devin implementation.
- No migration of financial tools into Devin/MCP and no native Devin subagents in version 1.
- No strategy changes, broker integration, real orders, performance promises, or new backtesting system.
- No private Windsurf/Devin endpoints, credential extraction, billing bypass, global configuration edits, or automatic paid fallback.

A small centralized provider/configuration patch is acceptable when evidence shows it is the simplest reliable solution. Avoiding every source edit is a preference, not a reason to build a much larger service.

## 2. Working agreement: one stage at a time

The user is the messenger, not the implementation engineer. Do not ask them to choose protocols, interpret stack traces, or invent commands.

Complete only the stage explicitly authorized in the most recent user prompt. Run its tests, create its report, and stop. A successful test does not authorize the next stage. Never mark a stage human-approved yourself.

For a blocker, finish all safe work still possible within the stage. Return the precise blocker, evidence, and the smallest next action. Do not repeatedly retry authentication, increase usage, or change architecture without review.

### Workspace records

After locating or safely creating the checkout, use:

```text
docs/devin-bridge/
    AGENT_GUIDE.md              # copy of this specification
    PROGRESS.md                # stage status and exact next action
    STAGE_0_REPORT.md
    STAGE_1_REPORT.md
    STAGE_2_REPORT.md
    STAGE_3_REPORT.md
    STAGE_4A_REPORT.md
    STAGE_4B_REPORT.md
    STAGE_5_REPORT.md
```

Create reports only when their stage is executed. A small progress table is enough; do not build a new workflow framework.

Use these progress states: `not_started`, `in_progress`, `ready_for_review`, `blocked`, `approved`. Record approval only from an explicit relayed user/reviewer instruction. Preserve the baseline commit and the chosen transport/model/configuration fingerprint for reproducibility.

Keep raw transcripts, runtime configurations, fixtures containing private data, and credentials out of git. Store sanitized evidence locally and identify its paths in reports. Keep generated runtime files separate from source and from the user's real reports, memories, and checkpoints.

### Usage boundaries

The limits below count **runtime Devin prompt submissions**, including retries and structured-output fallback attempts. An ACP process can contain many submissions; counting process launches is insufficient. These limits do not count the user's separate coding-agent conversation implementing this project.

| Stage | Runtime Devin submissions authorized after that stage is explicitly approved |
|---|---:|
| 0: inspect | 0 |
| 1: feasibility | At most 12 total |
| 2: implementation | 0; use fakes |
| 3: integration regression | 0; use fakes |
| 4A: narrow live application run | At most 30, for one run |
| 4B: full live application run | At most 60, for one run; separate approval required |
| 5: documentation and handoff | 0 unless the user separately authorizes a manual live run |

These are engineering safeguards, not dollar caps or estimates. A single Devin turn may include internal inference not exposed by the interface. Never report unavailable usage as zero or promise unlimited subscription usage.

Enforce the counter outside model-generated instructions, before every submission. Disable automatic transport retries initially. Existing application fallback attempts must share the same counter. Default to one active runtime request, a 180-second deadline per submission, and no native subagents. A timeout or exhausted budget is a visible failure, not authorization to spend more.

## 3. Facts verified online, and facts still to verify locally

The inspected upstream README describes a key-optional `openai_compatible` provider and both `tradingagents` and `python -m cli.main` entry points. [S1] The inspected model client selects Chat Completions for that provider and supports a custom endpoint. [S2] These observations concern the inspected upstream `main`, not necessarily the user's checkout.

Model construction is centralized in `TradingAgentsGraph`, which also supplies a model to reflection. [S3] The Market Analyst uses `bind_tools` and inspects returned `tool_calls`. [S4] Structured-output helpers bind schemas and can fall back to free text. [S5]

Devin's command reference documents non-interactive print mode, prompt files, configuration selection, authentication status, model listing, and an ACP stdio server using JSON-RPC. [S6] ACP defines an agent conversation lifecycle, not a drop-in Chat Completions interface. [S7]

Configuration is layered: an empty working directory or one custom configuration file must not be assumed to remove inherited rules, hooks, MCP servers, or permissions. Verify actual behavior using the installed version and the configuration documentation. [S8][S9]

**Unproven:** whether this installed Devin version can be constrained and translated reliably enough to preserve TradingAgents' model contracts. Stage 1 exists to prove or disprove that before a substantial implementation.

## 4. Architecture decision: evaluate, then implement only one

### Candidate A: local Chat Completions bridge

TradingAgents keeps its existing `openai_compatible` provider. A loopback-only service translates its requests into Devin CLI operations, then translates validated results back.

```text
TradingAgents -> local HTTP bridge -> Devin CLI
```

Prefer this candidate when it works through existing configuration and its required HTTP surface is small. Target the pinned TradingAgents request subset, not every feature of the OpenAI API. An external bridge may require no application source edits, but that is not established until tested.

The current inspected client path suggests `/v1/chat/completions`; confirm by capturing requests locally with fake responses. Do not build `/v1/responses` or a model catalog endpoint without an actual requirement. [S2]

Bind only to loopback. Validate request size and model aliases; do not accept arbitrary executable paths, shell commands, working directories, or callback destinations from HTTP requests. Disable permissive cross-origin access and reject unexpected hosts/origins. On a shared machine, protect the endpoint with a locally generated secret when needed. That secret is local service protection, not a paid LLM-provider API key.

### Candidate B: direct LangChain-compatible provider

Add one model adapter and minimal registration/configuration integration. Keep all existing agent factories and graph routing unchanged.

```text
TradingAgents -> Devin-backed chat-model adapter -> Devin CLI
```

Prefer this when a small provider patch is simpler than the HTTP service, or the user's pinned revision lacks the necessary custom-endpoint support. Do not implement a duck-typed `invoke()` wrapper that ignores `bind_tools`, structured output, callbacks, or the model return types.

### Transport choice is independent

Either candidate may use ACP or non-interactive print mode. Evaluate documented capabilities and installed help. Choose one transport for the first implementation; do not build both for completeness.

ACP can offer structured lifecycle events, but those events are not automatically external Python-function requests. Print mode can be simpler, but only use a proven method of separating the final response from banners, status text, and errors. Do not invent Claude-style JSON/schema flags for Devin.

If neither transport can pass the compatibility and isolation tests, report that specific limitation. Do not quietly switch to a node rewrite, MCP migration, IDE automation, or direct API keys.

## 5. Compatibility contract

These requirements apply regardless of architecture.

### 5.1 One request means one model response, not a whole trading workflow

For the first implementation, start a fresh Devin session for every model request and provide the complete relevant message history supplied by TradingAgents. A persistent ACP process is acceptable only with new, isolated sessions. Never resume the coding agent's conversation or reuse one session across analyst roles, tickers, or runs.

Keep message order, roles, content, tool names, tool-call IDs, arguments, and tool results. Preserve the analysis date from the original prompt. Serialize safely; delimit embedded messages and tool results as data. Do not summarize, silently truncate, or rewrite TradingAgents' domain instructions.

If a transport only accepts one prompt, document that serializing roles is not identical to native role-priority enforcement. Add representative role-preservation and untrusted-tool-content tests; do not claim those tests prove perfect prompt-injection resistance.

### 5.2 External tools stay external

A valid model response may request a named function with arguments. The compatibility layer validates and returns that request to the existing TradingAgents/LangGraph tool path. It must not execute the function itself.

Test this complete cycle:

```text
1. Existing client sends messages and a bound Python-tool schema.
2. Devin returns a machine-readable request for that tool.
3. Adapter returns the normal AI message/tool_calls structure.
4. Existing LangGraph ToolNode executes the Python tool exactly once.
5. The resulting ToolMessage, including its call ID, is sent back.
6. Devin answers using the actual returned value.
```

The first test uses a harmless test-only Python function returning a freshly generated, non-secret marker. The marker must be generated after the tool request and only placed in the tool result. A guessed/static answer or asking the model to do arithmetic is not proof of tool execution.

Validate tool names against the bound request, arguments against the schema, and tool-result IDs against the conversation. Preserve valid multiple calls and result ordering. Test malformed JSON, unknown tools, invalid types, missing results, and mismatched IDs offline.

Support the `tool_choice` forms actually emitted by the installed client. Explicitly reject unsupported forms rather than ignoring them. A structured-output schema may itself be represented as a function; leave its interpretation to the original client's structured-output parser, not the financial ToolNode.

Do not forward Devin's own ACP tool-activity notifications as if they were requests for TradingAgents to execute. ACP normally describes actions performed by the agent's own runtime. [S7]

### 5.3 Possible internal response envelope

When native output is insufficient, a strictly validated adapter-internal envelope is an acceptable experiment:

```json
{"kind":"final","content":"The assistant response."}
```

or:

```json
{"kind":"tool_calls","calls":[{"name":"fixture_lookup","arguments":{"key":"sample"}}]}
```

This is a proposed private bridge format, not a documented Devin feature. The adapter translates it into the existing client protocol, including unique call IDs and appropriate completion reasons. TradingAgents' agents must never need to know this envelope exists.

Reject incomplete or ambiguous output. Do not extract arbitrary braces from free text, execute generated code, use `eval`, or manufacture missing financial values. Any format-repair attempt must be explicit, counted, bounded, and reported; initially prefer a clear failure over automatic repair.

### 5.4 Structured output must really parse

Discover the schemas used in the checkout. The inspected upstream includes `ResearchPlan`, `TraderProposal`, `PortfolioDecision`, and `SentimentReport`; confirm actual call sites rather than assuming every schema is invoked the same way. [S5][S10]

Test through the real model wrapper and its `with_structured_output` path. Assert the resulting object validates against the actual schema and renders through the existing renderer when applicable. A JSON-looking string or successful free-text fallback is not a structured-output pass.

Do not remove upstream fallbacks. Record their use and include every fallback submission in usage limits. Add tests detecting fallback so it cannot hide a broken adapter.

### 5.5 Lifecycle, limits, and observability

- Final output is valid only after the transport completes successfully. Reject auth errors, nonzero exits, cancelled turns, token-limit termination, and missing final output.
- Keep diagnostics separate from model content. For ACP, parse the documented event types and completion result; do not concatenate planning or private-reasoning events into the answer.
- Use subprocess argument arrays, not shell interpolation. Use private temporary files where needed and clean up only owned files/processes.
- On timeout, Ctrl+C, or an HTTP disconnect, terminate/cancel owned work and prevent orphan processes. Preserve the application's existing checkpoint behavior.
- Log request ID, stage, model alias, transport, timing, validation status, and counted attempts. Redact credentials and sensitive content by default.
- If tokens or cost are unavailable, say `unavailable`. Do not invent usage, map character counts to billed tokens, or report a zero-cost run.
- Inventory sampling, output-token limits, stop sequences, streaming, and other client parameters. Implement, reject, or clearly disclose each unsupported behavior. A prompt asking for a short response is not an enforced `max_tokens` limit.
- Graph progress streaming is not necessarily token streaming. Inspect actual outgoing requests before implementing HTTP streaming. Test existing CLI progress/callbacks without claiming unsupported token-level streaming. [S11]

### 5.6 Runtime isolation

The implementing coding agent may edit code. The Devin subprocess serving model requests must not be allowed to do so.

Use a disposable runtime directory outside the source checkout and a documented, restrictive runtime configuration. Disable or deny native shell/edit/web/MCP/delegation actions for the model-only path; do not rely only on a prompt saying not to use them. Deny unsupported ACP permission requests rather than auto-approving them.

Inspect inheritance of user rules, project rules, imports, hooks, plugins, skills, MCP servers, and subagents. Configuration layering means an empty server list does not necessarily clear inherited servers. Prove the actual settings or mark isolation unproven. [S8][S9]

Allow only the local inputs needed for the request and the normal authentication/runtime operations required by Devin itself. Do not claim that a prompt-level restriction is an operating-system sandbox.

Do not modify global Devin settings, move/copy credential stores, expose environment dumps, or bypass organization controls. A workspace-trust adjustment, if essential, must be documented, per-run, and limited to the disposable workspace; do not globally trust the source tree.

For tests requiring no direct LLM keys, scrub only test-process credentials, account for `.env` loading, and instrument the Python model-client routes. Do not delete the user's keys. Devin itself still needs its normal network/authentication path; this is not an offline-inference design.

## 6. Stage-by-stage execution and tests

### STAGE 0 - Inspect the real environment; do not implement

**Purpose:** Establish facts and recommend the smallest integration.

1. Inspect the current workspace and repository instructions. Preserve unrelated changes. If this is not a TradingAgents checkout, locate an existing checkout within the supplied workspace or clone the official public repository into a new, non-conflicting directory. Do not overwrite anything or create a hosted fork.
2. Record OS, shell, whether execution is local/remote/containerized, repository path, origin, branch, exact commit, working-tree status, Python/package versions available, and relevant agent instructions. Sanitize remote URLs that contain credentials.
3. Locate `devin` using the OS-appropriate command. Read its help, then use documented/installed-help commands to inspect its version, authentication status, available models, print support, ACP support, and configuration behavior. Metadata checks are allowed; model prompts are not. Report which environment owns the authenticated session.
4. If the coding agent runs in a cloud/container environment without the user's local CLI/session, report that mismatch. Do not transfer tokens from the local machine. Supply the smallest normal installation/login or local-terminal action with an exact command and working directory.
5. Inspect the model factory, provider registry, CLI provider selection, model validation/capabilities, message format, tool bindings, structured-output helpers, callbacks, reflection, memory, checkpoints, and any other LLM calls, including data-vendor paths. Report all places that could still request direct LLM credentials.
6. Determine the existing CLI launch command and the smallest offline baseline-test command. Run only tests verified not to contact model/data services and only when dependencies are available. Otherwise report `NOT RUN` with the reason; do not install/change dependencies during this stage.
7. Identify candidate architecture, transport, current/default permitted model, required source edits, likely parameter gaps, and a safe runtime isolation method. Do not select a more expensive model tier silently.
8. Copy this guide into `docs/devin-bridge/AGENT_GUIDE.md`, write `PROGRESS.md` and the Stage 0 report. Documentation and sanitized inspection evidence are the only intended changes.

**Tests now:** metadata/help checks and an available, inspected offline baseline. No `devin -p`, no ACP prompt, no market analysis.

**Gate:** clear execution environment; exact baseline; evidence-backed candidate; blockers and any user action explicitly identified. Installation/authentication blockers do not invalidate the completed code inspection, but Stage 1 must not start until resolved.

### STAGE 1 - Prove model compatibility in a disposable prototype

**Prerequisite:** Explicit approval of Stage 0 and this stage's limit of 12 runtime submissions.

Create a small isolated prototype and tests, not a production rewrite. Local virtual environments and project-scoped dependencies are allowed now; record changes and do not use global installations or `sudo`. Use the selected architecture/transport only.

Capture a representative request from the actual TradingAgents client using fake transport first. Confirm the required protocol surface. Establish runtime isolation before any live prompt.

Run these tests, keeping a submission ledger:

| Test | Method | Required evidence |
|---|---|---|
| PLAIN | Ask the real CLI for a supplied unique marker through the prototype | Correct final content, success status, fresh session, no native tools |
| TOOL | Bind a test-only tool through the real client; execute it through the original ToolNode; send its fresh marker back | Normal tool-call object; exactly one Python execution; matched call ID; answer uses returned marker |
| SCHEMA | Exercise each schema-bearing path required by the checkout | Actual parsed schema instance; fallback counter remains zero |
| ISOLATION | Two unrelated requests with different non-secret markers | Distinct sessions and no history/context added by the adapter across requests |
| VALIDATION | Use fake transport for malformed output, invalid tool names/arguments, timeout, cancellation and missing final output | Explicit failures, no fabricated success, no orphaned test process |

Representative role preservation, message-order, and untrusted-tool-content checks should also be included; use offline cases where possible. Report every test actually run, not just this checklist.

Do not test both full architectures. If the selected path fails, use remaining authorized submissions only for a narrowly justified diagnosis, then return the alternative recommendation. No automatic switch into a broad implementation.

**Gate:** plain replies, external tool round trip, and actual structured-output paths all work through a tested translation; isolation is demonstrated to the extent claimed; remaining limitations are explicit. Any unresolved core failure means `BLOCKED`, even if a stock-analysis paragraph looks convincing.

### STAGE 2 - Build the smallest maintainable integration

**Prerequisite:** Explicit acceptance of the Stage 1 evidence and chosen architecture.

Productize the proven adapter/bridge. Keep all domain prompts, graph edges, agent factories, financial-tool implementations, state schemas, and report renderers unchanged unless a specific, minimal exception is reviewed.

Implement configuration, model aliases, validated message translation, bounded process/session lifecycle, errors, cancellation, redaction, budgets, and needed client/callback compatibility. Keep implementation packaging simple; one local bridge module or one provider adapter is sufficient. Do not introduce a separate deployment platform.

Use distinct aliases such as `devin-quick` and `devin-deep` only as locally defined configuration, not as claims that these are real Devin model IDs. Map both initially to the single model proven in Stage 1. Unknown aliases must fail. Account for model-name capability heuristics in the installed TradingAgents client.

For a bridge, create a readiness check that makes no model call. For a direct adapter, create an equivalent configuration/CLI diagnostic. Supply clean start/stop commands, process-scoped settings, and opt-in live-test controls. Preserve the existing provider behavior and do not make tests contact Devin by default.

**Tests now:** offline unit/contract tests for normal text, full tool loop, multiple tools, schemas, errors, limits, authentication failure, no provider fallback, callbacks, cancellation, and session isolation. Assert the runtime submission counter remains zero.

**Gate:** maintainable implementation; test evidence; exact changed-file list; smallest justified source diff; baseline failures clearly separated from regressions.

### STAGE 3 - Test the original graph and Python CLI without live usage

**Prerequisite:** Stage 2 accepted.

Use deterministic fake Devin replies and fixture-backed financial data. Fixtures must replace external I/O in the test harness, not rewrite production tool behavior or prompts. Mark outputs clearly as test fixtures, not investment research.

Test the original graph with all default analyst roles enabled and existing minimal debate settings. Verify original state keys, expected role progression, tool nodes, structured-output rendering, final decision extraction, and saved reports. Compare graph/state/report structure to the pinned baseline, not LLM prose.

Exercise the auxiliary model paths found in Stage 0, including reflection when present. Test checkpoint interrupt/resume in a temporary cache, cancellation, and restoration of existing provider configuration. Do not clear the user's real checkpoints or memory.

Test the original Python CLI entry point with its existing interactive selections. Use a terminal-capable automated harness if available. A call to `.propagate()` alone is not a CLI test. If interactive coverage is unavailable, report it as untested and prepare exact manual steps; do not claim CLI completion.

Audit the Devin path with direct LLM-provider keys unavailable to the test process and other provider routes configured to fail. Check `.env`/configuration loading as well as initial environment variables. The existing framework may still legitimately use independent financial-data credentials.

**Tests now:** deterministic full-graph run, CLI run, report save, auxiliary paths, checkpoint recovery, cancellation, configuration rollback, and regression suite. Zero runtime Devin submissions.

**Gate:** unchanged workflow operates through the compatibility layer in offline tests. Every untested path is explicitly listed. Any needed domain-source change requires review rather than concealment inside a fixture.

### STAGE 4A - One narrow live run through the original CLI

**Prerequisite:** Stage 3 accepted and explicit approval of up to 30 runtime submissions.

Before launching, print a sanitized run manifest: commit, transport, endpoint or provider, quick/deep mapping, selected analysts, date, ticker, data vendors, output paths, submission limit, timeout, and runtime permissions.

Use one example ticker, one fixed date supported by the selected data source, the Market Analyst only, and the smallest existing debate/research settings. `AAPL` with an explicit historical date can be a connectivity test, not a recommendation. Keep the remaining original downstream graph active; do not skip managers or manually inject a final decision.

Use isolated report, memory, and checkpoint locations. Launch the original Python CLI and keep all financial tool execution in Python. Use live financial data only when actually available; a run with fixture data is a mixed/fixture test, not full live integration.

Capture evidence of a real financial-tool request/result round trip, graph completion, valid report saving, successful schema paths, and all model-request routes. Record measured latency, submissions, fallbacks, and unavailable usage fields. Do not make hidden direct LLM-provider calls.

A failed data vendor is a data-source failure, not proof that the bridge is broken. A valid report produced only by fallback does not prove structured-output compatibility. Report failures at the correct boundary.

**Gate:** one honest end-to-end run using the original CLI and the actual authenticated Devin runtime. Stop after this run regardless of success. No automatic retry of the whole analysis.

### STAGE 4B - One full live run with default analyst coverage

**Prerequisite:** Stage 4A accepted; a separate explicit approval authorizes up to 60 runtime submissions.

Enable all default analysts and keep the original minimal debate settings. Reuse the approved model/runtime configuration and one recorded ticker/date. Preflight all required data sources before spending model turns. Do not silently disable an analyst whose data source is unavailable.

Run once through the original CLI. Record each default role's completion, tool paths, structured outputs, final decision/report, and submission count. Do not require the opinion to match Stage 4A or another model.

A budget exhaustion produces `BLOCKED` or a documented partial test, not authorization to increase limits. Preserve checkpoints where supported and report what remains; do not claim the partial run is end-to-end success.

**Gate:** complete default-role path demonstrated live, with differences and untested optional settings documented. This establishes integration behavior, not trading accuracy or universal reliability.

### STAGE 5 - Handoff for a user with no framework knowledge

**Prerequisite:** Stage 4B accepted, or the reviewer explicitly approves a narrower handoff with stated limitations.

Write a short `RUNBOOK.md` in the documentation directory. Use exact paths, environment names, executable commands, menu labels, tested model aliases, and actual endpoints from this installation. No placeholders in the user-facing procedure unless the user genuinely must supply a secret through a normal secure flow.

For a bridge, show exactly:

```text
Terminal A: activate the verified environment and start the bridge.
Readiness check: exact command and expected success output; no inference.
Terminal B: activate the environment and start the original TradingAgents CLI.
Menus: exact provider, endpoint, model, analyst, date, and depth selections.
Finish: where the report is saved and how to stop both processes.
```

For a direct provider adapter, give the equivalent single-application instructions. Include the offline verification command, opt-in live test, how to inspect errors, what consumes usage, how to restore the original provider configuration, and how to uninstall only this integration.

List tested TradingAgents commit, Devin version, transport, model mapping, supported client features, known deviations, and skipped tests. Explain that independent data services may require credentials and that unavailable token/cost metrics are not zero.

**Tests now:** rerun offline checks and verify runbook commands that do not invoke a model. A user-driven live walkthrough requires separate authorization; do not silently repeat Stage 4.

## 7. Mandatory report to return after every stage

Write the same report to the stage report file and in the chat. Keep it roughly 500-900 words; refer to sanitized artifacts for bulky evidence. Never put secrets or raw authentication output in it.

Use the following exact boundary markers so the user can copy the entire block back to the reviewer:

```text
BEGIN TRADINGAGENTS_DEVIN_REPORT

Stage: STAGE_0 / STAGE_1 / STAGE_2 / STAGE_3 / STAGE_4A / STAGE_4B / STAGE_5
Status: READY_FOR_REVIEW or BLOCKED

1. Plain-English result
What worked, what failed, and what remains unproven.

2. Environment and baseline
OS; local/remote/container; repository path; commit; branch; dirty state;
Python environment; Devin version; authentication available yes/no/unknown.
Do not include tokens, account secrets, or credentials in remote URLs.

3. Architecture and source changes
Candidate/chosen integration; transport; tested model mapping;
exact files added/modified; whether any domain code or prompts changed.
For inspection-only stages, explicitly say no implementation was made.

4. Tests and evidence
For each test: exact command or test ID; OFFLINE, LIVE, or MIXED;
PASS, FAIL, or NOT RUN; observed result; sanitized evidence path.
A claimed pass needs observed evidence, not an implementation description.

5. Usage and safety
Runtime prompt submissions authorized/attempted/succeeded;
retries/fallbacks; native tool or subagent activity;
direct LLM-provider calls made yes/no/not-established;
credential values exposed no/incident-reported;
usage/cost unavailable when not measurable.

6. Limitations and blockers
Exact unsupported behavior or failure boundary. Separate environment,
model-contract, data-provider, and application failures.

7. USER ACTION REQUIRED
NONE, or the smallest exact action with working directory, command,
expected result, and what sanitized output to paste back.
Do not ask the user to make an architecture decision.

8. REVIEWER DECISION REQUIRED
Specific approval requested and recommended next stage.
Do not start it until explicitly authorized.

9. Resume point
Progress file path; current state; exact next task after approval;
any owned processes still running and how to stop them.

I stopped here. I did not start the next stage.

END TRADINGAGENTS_DEVIN_REPORT
```

## 8. Copy-paste prompts for the user

Send only one prompt at a time. Do not paste the entire sequence as an instruction to execute every stage. The reviewer may amend later prompts based on actual evidence.

### First prompt: Stage 0

```text
Read the attached TradingAgents_Devin_Bridge_Agent_Guide.md.
It supersedes the previous node-replacement/MCP implementation plan.

Goal: preserve TradingAgents, especially its existing Python CLI,
agents, graph, prompts, state and Python tools. Use my authorized,
authenticated Devin CLI instead of direct LLM-provider API keys.

Perform STAGE 0 ONLY. Inspect the workspace and existing instructions.
If needed, safely clone the official public TradingAgents repository
into a new, non-conflicting directory. Preserve all unrelated changes.
Do not create a hosted fork, push, implement a bridge, change source
or dependencies, alter global configuration, or run any model prompt.
Documentation and sanitized inspection evidence are allowed.

Determine the exact checkout/version, where you are executing, whether
my Devin executable and authenticated session are accessible there,
what its installed help supports, and the smallest viable integration.
Inspect tool calling, structured output, the original CLI, reflection,
and all other paths that could still need a direct LLM-provider key.

Copy the guide to docs/devin-bridge/AGENT_GUIDE.md. Create PROGRESS.md
and STAGE_0_REPORT.md there.

I EXPECT A REPLY. Return the completed report between
BEGIN TRADINGAGENTS_DEVIN_REPORT and END TRADINGAGENTS_DEVIN_REPORT,
using section 7 of the guide. Include observed evidence and any exact
user action required. I will copy that report to my reviewer.

STOP after Stage 0. Do not start Stage 1 or any live runtime test.
```

### After Stage 0 approval: Stage 1

```text
Stage 0 is approved subject to the review comments I provide with this
message. Read docs/devin-bridge/AGENT_GUIDE.md and PROGRESS.md again.

Execute STAGE 1 ONLY: a disposable feasibility prototype of the
approved integration/transport. Preserve application domain code.
You may use up to 12 runtime Devin prompt submissions TOTAL,
including retries and fallback attempts. Do not enable paid overages.

Prove plain output, the full original-client -> ToolNode -> model
round trip using a fresh tool-result marker, and actual schema parsing.
Establish runtime isolation first. Keep native Devin tools/subagents
out of the model path. Use fakes for failure tests.

I EXPECT A REPLY with the full bounded report from section 7,
including exact test evidence, attempted submissions, and limitations.
STOP for review. Do not implement Stage 2.
```

### After Stage 1 approval: Stage 2

```text
Stage 1 and its chosen architecture are approved subject to the
accompanying review comments. Follow AGENT_GUIDE.md and PROGRESS.md.

Execute STAGE 2 ONLY. Productize the proven compatibility layer with
the smallest maintainable change surface. Keep the original CLI,
graph, agents, domain prompts, tools, state, and reports intact.
Use fake runtime responses for all tests: zero live Devin submissions.
Do not implement a second transport or an alternative architecture.

I EXPECT A REPLY with the section 7 report, exact source diff,
offline test results, compatibility limitations, and next-stage request.
STOP for review. Do not start Stage 3.
```

### After Stage 2 approval: Stage 3

```text
Stage 2 is approved subject to the accompanying review comments.
Execute STAGE 3 ONLY from AGENT_GUIDE.md.

Test the original full graph and original Python CLI using fake Devin
responses and fixture-backed data. Include tool calls, schemas,
reports, reflection/auxiliary paths, checkpoint recovery, cancellation,
provider rollback, and absence of direct LLM-provider requests.
Zero live Devin submissions are authorized.

I EXPECT A REPLY with the section 7 report, clearly separating actual
CLI tests from Python API tests and identifying every untested path.
STOP for review. Do not run a live analysis.
```

### After Stage 3 approval: Stage 4A

```text
Stage 3 is approved subject to the accompanying review comments.
Execute STAGE 4A ONLY from AGENT_GUIDE.md.

I authorize one narrow live analysis through the ORIGINAL Python CLI,
using the approved model, one ticker/date, the Market Analyst only,
and the smallest existing debate settings. All original downstream
roles remain enabled. The limit is 30 runtime prompt submissions total,
including retries/fallbacks. Do not enable paid overages or extra agents.

Preflight data access and print the sanitized run manifest first.
Use isolated output/memory/checkpoint paths. Stop on the limit or a
material failure; do not repeat the entire run automatically.

I EXPECT A REPLY with the section 7 report and actual live evidence.
STOP for review. Do not start Stage 4B.
```

### After Stage 4A approval: Stage 4B

```text
Stage 4A is approved subject to the accompanying review comments.
Execute STAGE 4B ONLY from AGENT_GUIDE.md.

I authorize one live original-CLI run with all default analyst roles,
one ticker/date, the approved model, and minimal existing debate
settings. The limit is 60 runtime prompt submissions total, including
retries/fallbacks. Preflight data access. Do not silently drop analysts,
increase limits, enable overages, or repeat the run automatically.

I EXPECT A REPLY with the section 7 report and evidence for every
role, schema/report completion, submission counts, and limitations.
STOP for review. Do not run additional analyses.
```

### After Stage 4B approval: Stage 5

```text
Stage 4B is approved subject to the accompanying review comments.
Execute STAGE 5 ONLY from AGENT_GUIDE.md.

Create the novice-friendly RUNBOOK.md with commands and menu choices
verified against this actual installation. Explain start, readiness,
original CLI usage, report location, stop, errors, and rollback.
Use exact paths/values rather than making me invent configuration.
No new live runtime submissions are authorized.

I EXPECT A REPLY with the section 7 report, the runbook location,
tested version matrix, final offline test results, and known limits.
STOP. Do not publish, push, or perform a live trading analysis.
```

### Recovery prompt when a session ends or changes

```text
Read docs/devin-bridge/AGENT_GUIDE.md, PROGRESS.md, and the latest
stage report. Inspect the actual working tree and existing test evidence.
Do not assume the previous coding agent completed what it described.

Resume only the currently approved stage and only its remaining
recorded usage budget. If the budget cannot be reconstructed, do not
make new live requests. Do not rerun a completed live analysis or
advance past a review gate. Return the section 7 report when finished
or blocked, and stop for review.
```

## 9. Source inventory

Source facts were checked against these public primary sources on 2026-09-12. Revalidate against the user's pinned commit and installed CLI. Most repository links track `main`; convert relevant code references to commit-pinned links in the actual implementation reports. Requirements and stage budgets in this guide are proposed engineering choices, not claims that upstream already implements them.

[S1] TradingAgents README: custom endpoints and existing CLI entry points.
```text
https://github.com/TauricResearch/TradingAgents
```
[S2] OpenAI-compatible provider implementation and structured-output wrapper.
```text
https://raw.githubusercontent.com/TauricResearch/TradingAgents/main/tradingagents/llm_clients/openai_client.py
```
[S3] Central model construction, graph/tool integration, reflection wiring.
```text
https://raw.githubusercontent.com/TauricResearch/TradingAgents/main/tradingagents/graph/trading_graph.py
```
[S4] Market Analyst model/tool contract.
```text
https://raw.githubusercontent.com/TauricResearch/TradingAgents/main/tradingagents/agents/analysts/market_analyst.py
```
[S5] Existing structured-output binding and fallback behavior.
```text
https://raw.githubusercontent.com/TauricResearch/TradingAgents/main/tradingagents/agents/utils/structured.py
```
[S6] Official Devin command/flag reference, including print mode and ACP.
```text
https://docs.devin.ai/cli/reference/commands
```
[S7] ACP prompt lifecycle and agent tool activity.
```text
https://agentclientprotocol.com/protocol/v1/prompt-turn
```
[S8] Official Devin configuration and import/layering guidance.
```text
https://docs.devin.ai/cli/extensibility/configuration
https://docs.devin.ai/cli/reference/configuration/config-file
```
[S9] Official Devin permission rules.
```text
https://docs.devin.ai/cli/reference/permissions
```
[S10] Existing output schemas.
```text
https://raw.githubusercontent.com/TauricResearch/TradingAgents/main/tradingagents/agents/schemas.py
```
[S11] Original Python CLI progress and execution path.
```text
https://raw.githubusercontent.com/TauricResearch/TradingAgents/main/cli/main.py
```
[S12] Provider factory, capability heuristics, and configuration.
```text
https://raw.githubusercontent.com/TauricResearch/TradingAgents/main/tradingagents/llm_clients/factory.py
https://raw.githubusercontent.com/TauricResearch/TradingAgents/main/tradingagents/llm_clients/capabilities.py
https://raw.githubusercontent.com/TauricResearch/TradingAgents/main/tradingagents/default_config.py
```
