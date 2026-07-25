# AWS says a production agent is now two API calls. I tested that.

TL;DR: The new Amazon Bedrock AgentCore harness really does stand up a working agent with `CreateHarness` and `InvokeHarness`. But the two calls hide an IAM role with undocumented permissions, ~900 tokens of invisible prompt scaffolding you pay for on every invocation, two shadow resources you didn't ask for, and a Terraform provider that silently pretends one of them doesn't exist.

At AWS Summit New York this June, AWS shipped the AgentCore **managed harness** with a bold pitch: define your agent with one API call, run it with a second. No container to build, no framework to wire up, no agent loop to write. AWS handles identity, memory, tools, and observability.

I've heard "two API calls" before. Last year it was Lambda durable functions, and testing that pitch taught me that the interesting part of any new AWS primitive is the part the launch blog doesn't mention. So I did the same thing again: built the smallest real agent I could, then tried to manage it the way production infrastructure actually gets managed — with Terraform.

## The two calls work

Here's the entire agent definition:

```python
control = boto3.client("bedrock-agentcore-control")

harness = control.create_harness(
    harnessName="harness_probe",
    executionRoleArn=ROLE_ARN,
    model={"bedrockModelConfig": {
        "modelId": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        "maxTokens": 1024,
    }},
    systemPrompt=[{"text": "You are a concise research assistant."}],
)["harness"]
```

And the entire runtime:

```python
data = boto3.client("bedrock-agentcore")

resp = data.invoke_harness(
    harnessArn=harness["arn"],
    runtimeSessionId=uuid.uuid4().hex + uuid.uuid4().hex[:8],
    messages=[{"role": "user", "content": [{"text": question}]}],
)
for event in resp["stream"]:
    ...  # Converse-style stream: messageStart, contentBlockDelta, metadata
```

The harness went READY in under a minute and streamed back a clean answer. No Dockerfile, no agent framework, no orchestration code. As a developer experience, this is genuinely the fastest path from nothing to a running agent I've seen on AWS.

That's the pitch. Now the asterisks.

## Asterisk 1: the SDK you have doesn't know this feature exists

My AWS CLI (v2.24, from early 2025) has no `bedrock-agentcore-control` commands at all. A boto3 from a few weeks before I started (1.42.77) was also missing every harness operation; 1.43.50 has them. If you follow the launch blog with anything but a fresh SDK, your first error arrives before your first API call. Pin your SDK versions — the same lesson durable functions taught me, repeating on schedule.

## Asterisk 2: the execution role needs permissions nobody documented

The pitch doesn't count the IAM role you must bring. Fine — every AWS service needs a role. But my first `InvokeHarness` died mid-stream with:

```
AccessDeniedException ... is not authorized to perform:
bedrock-agentcore:ListEvents on resource: ...:memory/harness_harness_probe_c02d-...
```

Two things about this error deserve attention. First, that memory resource: I never created it. The harness silently provisions a **managed memory resource** when you don't configure memory — it's real, it has an ARN, and it bills at $0.25 per thousand events. Second, the execution role needs `bedrock-agentcore` memory permissions to use it, and no launch material mentions this. The error also doesn't fail the request — it arrives as a `runtimeClientError` event *inside the stream*, so if your code doesn't consume the stream carefully, the invoke just looks empty.

While diagnosing this I found the harness had also quietly created an **agent runtime** resource. So "two API calls" actually provisions: a harness, an agent runtime, and a memory store. Two of those three are invisible unless you go looking.

## Asterisk 3: you pay for ~900 tokens you never wrote

The first invoke reported `inputTokens: 947` — for a one-line question and a two-sentence system prompt. That number wouldn't have surprised me at 60. So I measured, same one-line user message every time:

| Variation                              | inputTokens |
|----------------------------------------|-------------|
| Harness defaults (2-sentence prompt)   | 942         |
| `maxIterations=1`                      | 942         |
| System prompt overridden to one char   | 921         |
| One trivial inline tool added          | 984         |

The harness injects a fixed scaffold of roughly **905 tokens** into every invocation — its agent-loop instructions, riding on top of whatever you wrote. It's invariant to `maxIterations` and grows with each tool you attach.

Does it matter? At Haiku pricing the scaffold costs $0.0009 per call. For a support chatbot, irrelevant. For anything high-volume — a million calls is ~$900 of scaffold on Haiku, roughly triple on Sonnet — it's a real line item that appears nowhere in the pricing page, because it's billed as your own input tokens.

(One more thing the errors taught me: the harness runs `ConverseStream` underneath. Override the system prompt with whitespace and Converse's own "system field can't be blank" validation comes back at you.)

## Asterisk 4: Terraform can't see what the service created

This is the one that matters if you run infrastructure as code.

The provider has an `aws_bedrockagentcore_harness` resource, and the happy path works: `apply` created my harness in 3m01s, a no-op `plan` came back clean, and `import` round-trips by harness ID. Better than I expected for a four-week-old resource.

Then I looked at the state file. `GetHarness` returns the memory configuration the service attached by default:

```json
"memory": {"managedMemoryConfiguration": {"arn": "arn:aws:bedrock-agentcore:...:memory/harness_harness_probe_tf_..."}}
```

`terraform state show` returns... no memory attribute at all.

The provider's `memory` block only supports one of the API's three memory variants — bring-your-own memory ARN. The service default (`managedMemoryConfiguration`) and `disabled` can't be expressed in HCL, and until mid-July the provider crashed with `UnknownUnionMember` trying to read them back ([#48496](https://github.com/hashicorp/terraform-provider-aws/issues/48496)). On current v6.56.0 it no longer crashes — it **silently drops the memory config from state**. No error, no drift, nothing to plan. Terraform manages your harness while being structurally blind to a billable resource attached to it.

I'd argue the silent version is worse than the crash. A crash tells you something is wrong. A clean `plan` tells you everything is fine.

The bug's history is its own small lesson in reading issue trackers: #48496 was auto-closed by a PR that touched the same file but fixed something else entirely; a community member flagged the mistake a day later; the actual fix ([#48655](https://github.com/hashicorp/terraform-provider-aws/pull/48655)) — which flattens all three memory variants and makes the attribute computed — was still awaiting review as I wrote this. Until it merges, treat harness memory as unmanaged: whatever Terraform tells you, the service default is there, and it bills.

## Credit where due: teardown is clean

I expected the shadow resources to orphan on delete. They don't. `DeleteHarness` is asynchronous and slow — the harness lingers in `ListHarnesses` for about three and a half minutes — but when it goes, the auto-provisioned memory and agent runtime go with it. I verified with `ListMemories` and `ListAgentRuntimes` before and after. Deleting the Terraform-managed one via `destroy` behaves the same way.

## What it cost

Everything in this article — every probe, every failed invoke, the scaffold measurement matrix, the Terraform lifecycle, teardown tests — came to **under five cents**, nearly all of it Haiku input tokens. A harness has no standing charge; idle, the whole setup costs nothing. The cost story here isn't the total, it's the distribution: on every call you make, the harness's own scaffold is the biggest thing you're paying for until your prompts outgrow 900 tokens.

## Verdict

The pitch holds better than most. Two API calls genuinely produce a working, streaming, memory-equipped agent, and cleanup doesn't leak. If you're prototyping, this is the fastest agent surface AWS has ever shipped.

For production, go in knowing what the two calls don't say: bring a role with undocumented memory permissions, budget ~900 input tokens per call for scaffolding you can't see or shrink, and — until terraform-provider-aws#48655 merges — assume your IaC is blind to the memory resource the service attached on your behalf. The judgment the harness saves you from writing in code, you'll spend reading state files instead.

## Try it yourself

The probe scripts, Terraform config, and full findings log are on GitHub: **amrutp24/agentcore-harness-reality-check**. Both the SDK probe and the Terraform stack tear down completely; a full run costs a few cents.
