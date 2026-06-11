variable "aws_region" {
  description = "AWS region to deploy resources"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project name used to prefix all resources"
  type        = string
  default     = "cloud-cost-intelligence"
}

variable "slack_webhook_url" {
  description = "Slack incoming webhook URL for cost alerts"
  type        = string
  sensitive   = true
}

variable "alert_schedule" {
  description = "EventBridge cron for weekly Slack digest"
  type        = string
  default     = "cron(0 9 ? * MON *)"
}
