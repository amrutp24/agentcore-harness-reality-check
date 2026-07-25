"""Create the execution role the harness assumes.

The harness needs an IAM role that trusts the AgentCore service and can
invoke the Bedrock model. This is the prerequisite the "two API calls"
pitch doesn't count.

Usage: python scripts/00_bootstrap_iam.py
"""

import json

import boto3

PROFILE = "dev"
REGION = "us-east-1"
ROLE_NAME = "agentcore-harness-probe-role"

session = boto3.Session(profile_name=PROFILE, region_name=REGION)
iam = session.client("iam")
account_id = session.client("sts").get_caller_identity()["Account"]

trust_policy = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
            "Action": "sts:AssumeRole",
            "Condition": {
                "StringEquals": {"aws:SourceAccount": account_id},
            },
        }
    ],
}

permissions = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "InvokeModel",
            "Effect": "Allow",
            "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
            "Resource": "*",
        },
        {
            "Sid": "Logs",
            "Effect": "Allow",
            "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
            "Resource": "*",
        },
        {
            # Undocumented requirement: the harness auto-provisions a managed
            # memory resource and the execution role must be able to use it
            # (first invoke fails on bedrock-agentcore:ListEvents without this).
            "Sid": "ManagedMemory",
            "Effect": "Allow",
            "Action": ["bedrock-agentcore:*"],
            "Resource": f"arn:aws:bedrock-agentcore:{REGION}:{{account}}:memory/*",
        },
    ],
}
permissions["Statement"][-1]["Resource"] = permissions["Statement"][-1]["Resource"].format(account=account_id)

try:
    role = iam.create_role(
        RoleName=ROLE_NAME,
        AssumeRolePolicyDocument=json.dumps(trust_policy),
        Description="Execution role for the AgentCore harness probe",
    )
    print(f"created role {role['Role']['Arn']}")
except iam.exceptions.EntityAlreadyExistsException:
    role = iam.get_role(RoleName=ROLE_NAME)
    print(f"role already exists: {role['Role']['Arn']}")

iam.put_role_policy(
    RoleName=ROLE_NAME,
    PolicyName="harness-probe",
    PolicyDocument=json.dumps(permissions),
)
print("attached inline policy harness-probe")
print(f"\nexecution_role_arn = {role['Role']['Arn']}")
