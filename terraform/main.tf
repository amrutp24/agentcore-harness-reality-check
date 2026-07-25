terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.51.0"
    }
  }
}

provider "aws" {
  profile = var.aws_profile
  region  = var.aws_region
}

variable "aws_profile" {
  type    = string
  default = "dev"
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["bedrock-agentcore.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "harness" {
  name               = "agentcore-harness-tf-role"
  assume_role_policy = data.aws_iam_policy_document.assume_role.json
}

resource "aws_iam_role_policy" "harness" {
  name = "harness-permissions"
  role = aws_iam_role.harness.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "InvokeModel"
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
        Resource = "*"
      },
      {
        # Undocumented: the harness auto-provisions a managed memory resource
        # and the first InvokeHarness fails without access to it.
        Sid      = "ManagedMemory"
        Effect   = "Allow"
        Action   = ["bedrock-agentcore:*"]
        Resource = "arn:aws:bedrock-agentcore:${var.aws_region}:${data.aws_caller_identity.current.account_id}:memory/*"
      },
      {
        Sid      = "Logs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "*"
      }
    ]
  })
}

# Deliberately no `memory` block: the service then defaults to a managed
# memory configuration, which is the case terraform-provider-aws#48496
# cannot read back (UnknownUnionMember on every subsequent plan/apply).
resource "aws_bedrockagentcore_harness" "probe" {
  harness_name       = "harness_probe_tf"
  execution_role_arn = aws_iam_role.harness.arn

  model {
    bedrock_model_config {
      model_id   = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
      max_tokens = 1024
    }
  }

  system_prompt {
    text = "You are a concise research assistant. Answer in at most three sentences and say when you are unsure."
  }
}

output "harness_arn" {
  value = aws_bedrockagentcore_harness.probe.arn
}
