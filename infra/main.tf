# ── Provider ──────────────────────────────────────────────────

terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# ── S3 Bucket ─────────────────────────────────────────────────

resource "aws_s3_bucket" "cost_data" {
  bucket = "${var.project_name}-data-${data.aws_caller_identity.current.account_id}"

  tags = {
    Project     = var.project_name
    Environment = "production"
    ManagedBy   = "terraform"
  }
}

# Block all public access — cost data is sensitive
resource "aws_s3_bucket_public_access_block" "cost_data" {
  bucket = aws_s3_bucket.cost_data.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Get current AWS account ID (used for unique bucket name)
data "aws_caller_identity" "current" {}


# ── IAM Role for Lambda ───────────────────────────────────────

resource "aws_iam_role" "lambda_role" {
  name = "${var.project_name}-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })

  tags = {
    Project   = var.project_name
    ManagedBy = "terraform"
  }
}

# Lambda basic execution policy (CloudWatch Logs)
resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Custom policy: Cost Explorer read + S3 read/write
resource "aws_iam_role_policy" "lambda_custom" {
  name = "${var.project_name}-lambda-policy"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # Cost Explorer — read-only is all we need
        Effect = "Allow"
        Action = [
          "ce:GetCostAndUsage",
          "ce:GetCostForecast",
        ]
        Resource = "*"
      },
      {
        # S3 — only our specific bucket
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket",
        ]
        Resource = [
          aws_s3_bucket.cost_data.arn,
          "${aws_s3_bucket.cost_data.arn}/*",
        ]
      }
    ]
  })
}


# ── Lambda Function ───────────────────────────────────────────

resource "aws_lambda_function" "cost_analyzer" {
  filename      = "${path.module}/lambda.zip"
  function_name = "${var.project_name}-analyzer"
  role          = aws_iam_role.lambda_role.arn
  handler       = "lambda_handler.handler"
  runtime       = "python3.11"
  timeout       = 120 # Cost Explorer can be slow — 2 min timeout
  memory_size   = 512 # Pandas needs more memory than Lambda default

  # Pass secrets as environment variables — never hardcode in code
  environment {
    variables = {
      SLACK_WEBHOOK_URL = var.slack_webhook_url
      S3_BUCKET         = aws_s3_bucket.cost_data.bucket
      USE_MOCK_DATA     = "false" # Set to "true" for local testing
    }
  }

  source_code_hash = filebase64sha256("${path.module}/lambda.zip")

  tags = {
    Project   = var.project_name
    ManagedBy = "terraform"
  }
}


# ── EventBridge Rule ──────────────────────────────────────────

resource "aws_cloudwatch_event_rule" "weekly_trigger" {
  name                = "${var.project_name}-weekly-trigger"
  description         = "Triggers cost analysis every Monday at 9 AM UTC"
  schedule_expression = var.alert_schedule

  tags = {
    Project   = var.project_name
    ManagedBy = "terraform"
  }
}

resource "aws_cloudwatch_event_target" "lambda_target" {
  rule      = aws_cloudwatch_event_rule.weekly_trigger.name
  target_id = "CostAnalyzerLambda"
  arn       = aws_lambda_function.cost_analyzer.arn
}

# Give EventBridge permission to invoke the Lambda
resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.cost_analyzer.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.weekly_trigger.arn
}


# ── Outputs ───────────────────────────────────────────────────
# Outputs print useful values after terraform apply.
# Why outputs? So you don't have to log into the AWS console
# to find resource names/ARNs — they print right in the terminal.
output "lambda_function_name" {
  description = "Name of the deployed Lambda function"
  value       = aws_lambda_function.cost_analyzer.function_name
}

output "s3_bucket_name" {
  description = "Name of the S3 bucket storing cost data"
  value       = aws_s3_bucket.cost_data.bucket
}

output "eventbridge_rule_name" {
  description = "EventBridge rule that triggers weekly analysis"
  value       = aws_cloudwatch_event_rule.weekly_trigger.name
}

output "next_trigger_info" {
  description = "When the Lambda will next run"
  value       = "Every Monday at 09:00 UTC — ${var.alert_schedule}"
}
