"""Measure the harness's hidden prompt scaffold.

A one-line question with a 2-sentence system prompt billed 947 input
tokens on the first run. This script varies one knob at a time and
records inputTokens to isolate what the harness injects.

Usage: python scripts/02_measure_scaffold.py
"""

import uuid

import boto3

PROFILE = "dev"
REGION = "us-east-1"
HARNESS_NAME = "harness_probe"

session = boto3.Session(profile_name=PROFILE, region_name=REGION)
control = session.client("bedrock-agentcore-control")
data = session.client("bedrock-agentcore")

harness = next(
    h
    for h in control.list_harnesses()["harnesses"]
    if h["harnessName"] == HARNESS_NAME
)

QUESTION = "Reply with the single word: ok"


def invoke(label, **overrides):
    resp = data.invoke_harness(
        harnessArn=harness["arn"],
        runtimeSessionId=uuid.uuid4().hex + uuid.uuid4().hex[:8],
        messages=[{"role": "user", "content": [{"text": QUESTION}]}],
        **overrides,
    )
    usage = None
    for event in resp["stream"]:
        if "metadata" in event:
            usage = event["metadata"]["usage"]
    print(
        f"{label:<40} in={usage['inputTokens']:>5}  out={usage['outputTokens']:>4}"
    )
    return usage


print(f"harness: {harness['arn']}\n")
invoke("baseline (harness defaults)")
invoke("maxIterations=1", maxIterations=1)
invoke("empty systemPrompt override", systemPrompt=[{"text": " "}])
invoke(
    "one inline tool added",
    tools=[
        {
            "type": "inline_function",
            "name": "get_time",
            "config": {
                "inlineFunction": {
                    "description": "Returns the current time",
                    "inputSchema": {"type": "object", "properties": {}},
                }
            },
        }
    ],
)
