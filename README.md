# AgentCore Harness Reality Check

[![CI](https://github.com/amrutp24/agentcore-harness-reality-check/actions/workflows/ci.yml/badge.svg)](https://github.com/amrutp24/agentcore-harness-reality-check/actions/workflows/ci.yml)

📖 **Read the article:** [AWS says a production agent is now two API calls. I tested that.](https://builder.aws.com/content/3BnCQ3tNlxDCGakjdtowPexN1dJ/aws-says-a-production-agent-is-now-two-api-calls-i-tested-that)

AWS says the new Amazon Bedrock AgentCore **managed harness** turns a
production agent into two API calls: `CreateHarness` defines it,
`InvokeHarness` runs it. This project tests that claim end to end —
first with the raw SDK, then by managing the same harness the way
production infrastructure is actually managed: with Terraform.

Companion repo for an AWS Builder Center article (in progress).

## Layout

```
agentcore-harness-reality-check/
├── scripts/
│   ├── 00_bootstrap_iam.py     # The prerequisite the pitch doesn't count
│   ├── 01_create_and_invoke.py # The two calls, timed and logged
│   └── 99_cleanup.py           # Delete the harness + role
├── terraform/                  # Phase 2: same harness as IaC
└── NOTES.md                    # Findings log (gotchas, costs, bugs)
```

## Prerequisites

- AWS account with Bedrock model access for Claude Haiku 4.5 in a
  harness-supported region (us-east-1, us-west-2, ap-southeast-2, eu-central-1)
- Python 3.12+ and boto3 >= 1.43.50 — older SDKs (and AWS CLI builds from
  before mid-2026) do not have the harness APIs at all
- Terraform >= 1.5 for phase 2

## Run

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
.venv/Scripts/python scripts/00_bootstrap_iam.py   # note the role ARN
# paste the ARN into scripts/01_create_and_invoke.py
.venv/Scripts/python scripts/01_create_and_invoke.py
.venv/Scripts/python scripts/99_cleanup.py
```

## License

MIT

## Author

Amrut Pagidipally
