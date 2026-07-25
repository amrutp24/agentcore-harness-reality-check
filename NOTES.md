# Findings log

Raw material for the article. Every gotcha, surprise, and cost number goes
here with enough detail to reproduce it.

## Before touching AWS

- **AWS CLI v2.24.24 (early 2025) has no `bedrock-agentcore-control` harness
  commands at all.** Anyone following the launch blog with a CLI older than
  ~June 2026 gets `Invalid choice` errors. boto3 1.42.77 (a few weeks old)
  also lacks the Harness operations; 1.43.50 has them. Same "pin your SDK"
  lesson as durable functions.
- **It is not literally two API calls.** The control plane has 11 harness
  operations including `CreateHarnessEndpoint`. Before either "official"
  call you need an IAM execution role with a `bedrock-agentcore.amazonaws.com`
  trust policy (service principal to be verified against docs) and Bedrock
  invoke permissions. `InvokeHarness` also requires a `runtimeSessionId` the
  pitch never mentions.
- **`CreateHarness` required fields are only `harnessName` + `executionRoleArn`.**
  Everything else (model, prompts, tools, skills, memory, truncation) is
  optional — worth testing what the defaults actually are, especially which
  model you get if you don't specify one.
- **The memory config is a union** (`agentCoreMemoryConfiguration` |
  `managedMemoryConfiguration` | `disabled`), and the service default when you
  omit it is `managedMemoryConfiguration` — the exact case the Terraform
  provider cannot read back (hashicorp/terraform-provider-aws#48496,
  `UnknownUnionMember` on every plan/apply/import after create).

## First live run (2026-07-19, us-east-1, profile dev)

- **Bare model ID rejected.** `anthropic.claude-haiku-4-5-...` fails Converse
  with "on-demand throughput isn't supported" — you must use the inference
  profile ID (`us.anthropic.claude-haiku-4-5-20251001-v1:0`). The harness
  docs' model examples don't mention this.
- **CreateHarness response shape:** everything is nested under a `harness`
  key, and the ARN field is `arn` — while the data plane's InvokeHarness
  wants it as `harnessArn`. Same value, different field names across planes.
- **Harness reached READY in under ~60s** (was still CREATING at first poll,
  READY on re-run 5s later).
- **The invoke fails without undocumented memory permissions.** First
  InvokeHarness died mid-stream: the service had silently auto-provisioned a
  managed memory resource (`memory/harness_harness_probe_c02d-...`) and the
  execution role got `AccessDeniedException` on `bedrock-agentcore:ListEvents`
  against it. No launch material mentions the execution role needs
  bedrock-agentcore memory actions. Error surfaces as a `runtimeClientError`
  event *inside the stream*, not as a request failure — easy to miss if you
  don't consume the stream.
  - Note the auto-created memory resource is itself billable
    ($0.25/1k short-term events) and invisible until something breaks.
- **After adding `bedrock-agentcore:*` on `memory/*`: works end to end.**
  Streamed a clean Converse-style event stream (messageStart /
  contentBlockDelta / messageStop / metadata).
- **~900 tokens of hidden prompt scaffold per call.** A one-line user message
  plus a 2-sentence system prompt reported `inputTokens: 947`. The harness
  injects its own system scaffolding (agent loop instructions, presumably
  tool/skill plumbing) into every invocation — you pay for it on every call.
  Latency 1391 ms for 80 output tokens.
- IAM propagation: policy update needed ~15s before the invoke stopped 403ing.

## Terraform phase (2026-07-19, provider v6.56.0, Terraform v1.11.2)

The story moved while we were building. What I measured:

- **Create/read/import all work now** — `apply` (3m01s), no-op `plan`, and
  `state rm` + `import` (by harness ID) all succeed on v6.56.0. The
  UnknownUnionMember crash from #48496 is no longer reproducible.
- **But the fix is an illusion: the provider silently drops the memory
  config it can't flatten.** GetHarness returns
  `memory.managedMemoryConfiguration` (with a real, billable memory ARN);
  the Terraform state contains no memory attribute at all. No error, no
  drift — Terraform just doesn't know the memory exists.
- **You cannot express the service default in HCL.** The `memory` block
  only supports `agentcore_memory_configuration` (bring-your-own memory
  ARN). `managedMemoryConfiguration` (the default!) and `disabled` are not
  in the schema, so a plain harness can never have its memory round-trip.
- **Issue #48496 was closed by the wrong PR.** #48654 (a VPC-endpoint PR
  that touched harness.go) auto-closed it on 2026-07-15; a commenter
  (Brodan, 2026-07-16) flagged the mistake. The real fix — all three union
  members flattened, `memory` Optional+Computed — is PR #48655
  (jesseturner21), still open awaiting review as of 2026-07-19.
- **Shadow infrastructure:** the "two API calls" actually provision an
  agent runtime (`runtime/harness_harness_probe_tf-...`) and a managed
  memory resource, both visible in GetHarness/state inspection, neither
  mentioned in the pitch. The memory is billable ($0.25/1k events) and
  invisible to Terraform per the above.
- Also observed: `allowed_tools = ["*"]` is the computed service default.
- Other open provider issues still relevant: #48159 (inconsistent result
  after apply on computed environment fields), #48363 (missing
  `additionalParams` in `bedrock_model_config`).

**Contribution opportunity (vetted per PR-first policy):** the fix PR
#48655 exists, so no code contribution needed there — but nobody has
posted the v6.56.0 empirical behavior (silent memory drop replacing the
crash) on #48496/#48655. A reproduction comment with these findings is a
genuine contribution and citable in the article.

## Scaffold measurement (2026-07-19, 6 invokes total, <1¢)

Same one-line user message ("Reply with the single word: ok") every time:

| Variation                        | inputTokens |
|----------------------------------|-------------|
| Harness defaults (2-sentence SP) | 942         |
| maxIterations=1                  | 942         |
| systemPrompt override = "x"      | 921         |
| + one inline tool (empty schema) | 984         |

- **The fixed scaffold is ~905 tokens** (921 minus the 1-char prompt and
  ~10-token user message). Injected into every call, invariant to
  maxIterations. Each tool adds its normal Converse toolConfig tokens
  (+42 for a trivial one).
- Cost of the scaffold alone: ~$0.0009/call on Haiku 4.5 ($1/MTok in) —
  ~$900 per million calls, roughly 3x that on Sonnet. Fine for a chatbot,
  real money for high-volume pipelines.
- **The harness runs ConverseStream under the hood.** A whitespace-only
  systemPrompt override fails with Converse's "system field can't be
  blank" validation, and the error helpfully leaks the region and model id.
  Errors from the underlying Bedrock call surface as `runtimeClientError`
  events inside the stream.

## Teardown behavior

- **DeleteHarness does NOT orphan the shadow resources.** The harness
  lingers in ListHarnesses for ~3.5 min after DeleteHarness (async), and
  when it disappears, its auto-provisioned memory and agent runtime are
  gone with it. Cleanup is correct — just slow and invisible while it runs.

## To verify (Terraform phase)

- [x] DeleteHarness cleans up the auto-provisioned runtime + memory
      (~3.5 min, async; verified via ListMemories/ListAgentRuntimes)
- [ ] Does PR #48655 build + fix the round-trip? (could test locally with
      a provider dev override)

## To verify

- [x] Execution role service principal: `bedrock-agentcore.amazonaws.com`
      (confirmed — assumed-role session named `BedrockAgentCore-<uuid>`)
- [x] `runtimeSessionId`: a 40-char hex string works
- [ ] What model a bare `CreateHarness` defaults to
- [x] `CreateHarnessEndpoint` is NOT needed for a basic invoke — invoking the
      harness ARN directly works (endpoints presumably for versioned/aliased
      deployments; confirm in phase 2)
- [ ] Cost per invoke — token side: 947 in / 80 out per minimal call; still
      need the runtime vCPU-second and memory-event charges from Cost Explorer
      after a day
- [ ] What exactly is in the ~900-token hidden scaffold (try maxIterations=1,
      no tools, compare inputTokens)
