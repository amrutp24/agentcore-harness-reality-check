"""The claim under test: a production agent is two API calls.

Call 1: CreateHarness (control plane) defines the agent.
Call 2: InvokeHarness (data plane) runs it and streams events back.

This script makes exactly those two calls (plus a status poll, which
the pitch also doesn't count) and records everything that happens.

Usage: python scripts/01_create_and_invoke.py
"""

import time
import uuid

import boto3

PROFILE = "dev"
REGION = "us-east-1"
HARNESS_NAME = "harness_probe"
MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"  # bare model ID fails: on-demand needs the inference profile
ROLE_NAME = "agentcore-harness-probe-role"  # created by 00_bootstrap_iam.py

session = boto3.Session(profile_name=PROFILE, region_name=REGION)
control = session.client("bedrock-agentcore-control")
data = session.client("bedrock-agentcore")

account_id = session.client("sts").get_caller_identity()["Account"]
EXECUTION_ROLE_ARN = f"arn:aws:iam::{account_id}:role/{ROLE_NAME}"

# ---- Call 1: define the agent -------------------------------------------
# The response nests everything under "harness", and the ARN field is
# "arn" — not "harnessArn" like the data plane's InvokeHarness expects.
existing = [
    h
    for h in control.list_harnesses().get("harnesses", [])
    if h["harnessName"] == HARNESS_NAME
]
if existing:
    harness = existing[0]
    print(f"harness already exists -> {harness['arn']}")
else:
    harness = control.create_harness(
        harnessName=HARNESS_NAME,
        executionRoleArn=EXECUTION_ROLE_ARN,
        model={"bedrockModelConfig": {"modelId": MODEL_ID, "maxTokens": 1024}},
        systemPrompt=[
            {
                "text": "You are a concise research assistant. Answer in at most "
                "three sentences and say when you are unsure."
            }
        ],
    )["harness"]
    print(f"CreateHarness -> {harness['arn']}")
harness_arn = harness["arn"]

# The pitch doesn't mention this part: wait until it's actually usable.
t0 = time.time()
while True:
    desc = control.get_harness(harnessId=harness["harnessId"])["harness"]
    status = desc["status"]
    if status != "CREATING":
        break
    time.sleep(5)
print(f"  status {status} after {time.time() - t0:.0f}s of polling")

# ---- Call 2: run it -------------------------------------------------------
resp = data.invoke_harness(
    harnessArn=harness_arn,
    runtimeSessionId=uuid.uuid4().hex + uuid.uuid4().hex[:8],  # min length TBD
    messages=[
        {
            "role": "user",
            "content": [{"text": "What did AWS announce at Summit New York 2026?"}],
        }
    ],
)

print("\nInvokeHarness stream:")
for event in resp["stream"]:
    print(event)
