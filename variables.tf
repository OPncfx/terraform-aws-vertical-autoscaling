data "aws_caller_identity" "current" {}

variable "prefix" {
  description = "Prefix for the resources"
  type        = string
  default     = "vertical-autoscale"
}

variable "description" {
  description = "Description of the Lambda function"
  type        = string
  default     = "Scale up containers when alarm triggered"

}

variable "tags" {
  description = "Tags to apply to the resources"
  type        = map(string)
  default = {
    Name = "vertical-autoscale-lambda"
  }
}

variable "metrics" {
  description = "Metrics to monitor"
  type        = list(map(string))
}

variable "sns_topic_for_alarm_action" {
  description = "SNS topic to send alarm action"
  type        = string
  default     = null
}