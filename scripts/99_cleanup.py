"""Delete everything the probe created: the harness and the IAM role.

Usage: python scripts/99_cleanup.py
"""

import boto3

PROFILE = "dev"
REGION = "us-east-1"
HARNESS_NAME = "harness_probe"
ROLE_NAME = "agentcore-harness-probe-role"

session = boto3.Session(profile_name=PROFILE, region_name=REGION)
control = session.client("bedrock-agentcore-control")
iam = session.client("iam")

for harness in control.list_harnesses().get("harnesses", []):
    if harness.get("harnessName") == HARNESS_NAME:
        control.delete_harness(harnessId=harness["harnessId"])
        print(f"deleted harness {harness['harnessId']}")

try:
    iam.delete_role_policy(RoleName=ROLE_NAME, PolicyName="harness-probe")
    iam.delete_role(RoleName=ROLE_NAME)
    print(f"deleted role {ROLE_NAME}")
except iam.exceptions.NoSuchEntityException:
    print(f"role {ROLE_NAME} already gone")
