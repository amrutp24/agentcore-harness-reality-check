# AWS says a production agent is now two API calls. I tested that.

TL;DR: The new Amazon Bedrock AgentCore harness really does stand up a working agent with CreateHarness and InvokeHarness. It also hides an IAM role with undocumented permissions, about 900 tokens of invisible prompt scaffolding you pay for on every call, two resources you never asked for, and a Terraform provider that pretends one of them doesn't exist.

At AWS Summit New York this June, AWS shipped the AgentCore managed harness with a bold pitch: define your agent with one API call, run it with a second. No container to build, no framework to wire up, no agent loop to write.

I've heard "two API calls" before. Last year it was Lambda durable functions, and testing that pitch taught me that the interesting part of any new AWS primitive is the part the launch blog skips. So I did the same thing again. I built the smallest real agent I could, then tried to manage it the way production infrastructure actually gets managed: with Terraform.

## The two calls work

Here is the entire agent definition:

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

The harness went READY in under a minute and streamed back a clean answer. No Dockerfile, no agent framework, no orchestration code. This is the fastest path from nothing to a running agent I've used on AWS.

That's the pitch. Here's what it leaves out.

## Your SDK doesn't know this feature exists

My AWS CLI (v2.24, from early 2025) has no bedrock-agentcore-control commands at all. A boto3 from a few weeks before I started (1.42.77) was missing every harness operation too. 1.43.50 has them. If you follow the launch blog with anything but a fresh SDK, your first error arrives before your first API call. Durable functions taught me the same lesson: when the feature is this new, pin the SDK and keep it current.

## The execution role needs permissions nobody wrote down

The pitch doesn't count the IAM role you have to bring. Fine, every AWS service needs a role. But my first InvokeHarness died mid-stream with:

```
AccessDeniedException ... is not authorized to perform:
bedrock-agentcore:ListEvents on resource: ...:memory/harness_harness_probe_c02d-...
```

Look at that resource. I never created a memory resource. The harness provisions one for you when you don't configure memory, and it's real: it has an ARN and it bills at $0.25 per thousand events. The execution role needs bedrock-agentcore permissions on it, and I haven't found that requirement documented anywhere. The error also doesn't fail the request. It arrives as a runtimeClientError event inside the stream, so if your code doesn't consume the stream carefully, the invoke just looks empty.

While digging into this I found the harness had also quietly created an agent runtime resource. So "two API calls" actually provisions a harness, an agent runtime, and a memory store. Two of those three are invisible unless you go looking.

## You pay for about 900 tokens you never wrote

My first invoke reported 947 input tokens. The question was one line. The system prompt was two sentences. That number should have been around 60, so I measured, sending the same one-line message every time:

| Variation | inputTokens |
| --- | --- |
| Harness defaults (2-sentence prompt) | 942 |
| maxIterations=1 | 942 |
| System prompt overridden to one char | 921 |
| One trivial inline tool added | 984 |

The harness injects a fixed scaffold of roughly 905 tokens into every invocation. It's the harness's own agent-loop instructions, sitting on top of whatever you wrote. Setting maxIterations to 1 doesn't shrink it, and every tool you attach adds its usual Converse token cost on top (+42 for a trivial one).

At Haiku pricing the scaffold costs $0.0009 per call, so a support chatbot won't notice. A million calls is about $900 of scaffold on Haiku and roughly triple that on Sonnet, billed as your own input tokens, so a high-volume pipeline will. You won't find this number on the pricing page. It only shows up when you read the usage block.

One more thing the errors taught me: the harness runs ConverseStream underneath. Override the system prompt with whitespace and Converse's own "system field can't be blank" validation comes straight back at you.

## Terraform can't see what the service created

This is the part that matters if you run infrastructure as code.

The provider has an aws_bedrockagentcore_harness resource, and the happy path works. Apply created my harness in 3m01s, a no-op plan came back clean, and import round-trips by harness ID. Better than I expected for a resource that's four weeks old.

Then I compared the API against the state file. GetHarness returns the memory the service attached by default:

```json
"memory": {"managedMemoryConfiguration": {"arn": "arn:aws:bedrock-agentcore:...:memory/harness_harness_probe_tf_..."}}
```

Ask Terraform the same question:

```
$ echo "aws_bedrockagentcore_harness.probe.memory" | terraform console
tolist([])
```

The provider's memory block only models one of the API's three memory variants, the one where you bring your own memory ARN. The service default (managedMemoryConfiguration) and disabled aren't in the schema. Until mid-July the provider crashed trying to read them back (issue [#48496](https://github.com/hashicorp/terraform-provider-aws/issues/48496), UnknownUnionMember). On the current v6.56.0 it no longer crashes. It drops the memory from state and says nothing.

I'd argue the silent version is worse than the crash. A crash tells you something is wrong. A clean plan tells you everything is fine, while a billable resource sits attached to your harness outside Terraform's view. And since disabled isn't in the schema either, you can't opt out through Terraform. HCL currently has no way to say "no memory."

The bug's history is a small lesson in reading issue trackers. #48496 was auto-closed by a PR that touched the same file but fixed something else. A community member flagged the mistake a day later. The actual fix ([#48655](https://github.com/hashicorp/terraform-provider-aws/pull/48655)), which models all three memory variants and makes the attribute computed, was still waiting for review when I wrote this. Until it merges, treat harness memory as unmanaged: whatever Terraform tells you, the default is there and it bills.

## One thing they got right: teardown

I expected the hidden resources to orphan on delete. They don't. DeleteHarness is asynchronous and slow (the harness lingers in ListHarnesses for about three and a half minutes), but when it goes, the memory and the agent runtime go with it. I checked with ListMemories and ListAgentRuntimes before and after, on both the SDK-created harness and the Terraform-managed one.

## What it cost

Everything in this article, including every failed invoke, the token measurements, the full Terraform lifecycle, and the teardown tests, came to under five cents. Almost all of it was Haiku input tokens. A harness has no standing charge, so the whole setup costs nothing while idle. The number worth remembering is the per-call one: until your own prompts outgrow 900 tokens, the scaffold is the biggest thing on your token bill.

## Where this leaves you

The pitch holds better than most. Two API calls produce a working, streaming, memory-equipped agent, and cleanup doesn't leak. For prototyping, I have nothing faster on AWS.

For production, go in knowing what the two calls don't say. Bring a role with memory permissions the docs don't mention. Budget about 900 input tokens per call for scaffolding you can't see or shrink. And until terraform-provider-aws#48655 merges, assume your state file is blind to the memory resource the service attached on your behalf. The agent loop you didn't have to write still exists. Now it lives where you can't read it.

## Try it yourself

The probe scripts, Terraform config, and full findings log are on GitHub: [amrutp24/agentcore-harness-reality-check](https://github.com/amrutp24/agentcore-harness-reality-check). Both the SDK probe and the Terraform stack tear down completely. A full run costs a few cents.
