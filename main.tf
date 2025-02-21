module "lambda__this" {
  source  = "terraform-aws-modules/lambda/aws"
  version = "~> 6.0"

  function_name          = "${var.prefix}-lambda"
  description            = var.description
  handler                = "vertical_scale.lambda_handler"
  runtime                = "python3.13"
  timeout                = 30
  memory_size            = 128
  maximum_retry_attempts = 1
  source_path = [
    {
      path = "${path.module}/src/"
      commands = [
        ":zip . .",
      ]
    }
  ]

  create_package                          = true
  publish                                 = false
  create_current_version_allowed_triggers = true

  ignore_source_code_hash           = false
  cloudwatch_logs_retention_in_days = 180
  attach_network_policy             = false
  attach_policies                   = true
  number_of_policies                = 1
  policies = [
    "arn:aws:iam::aws:policy/AmazonECS_FullAccess",
  ]

  tags = var.tags
}


resource "aws_cloudwatch_metric_alarm" "this" {

  for_each = { for idx, metric in var.metrics : idx => metric }

  actions_enabled = true
  alarm_actions = [
    module.lambda__this.lambda_function_arn,
  ]
  alarm_description   = try(each.value.alarm_description, "")
  alarm_name          = try(each.value.alarm_name, "${var.prefix}-${each.value.name}-alarm")
  comparison_operator = "GreaterThanThreshold"


  dimensions = {
    ClusterName = each.value.cluster_name
    ServiceName = each.value.service_name
  }

  ## if in 5 minutes, 4 minutes are above 85 % cpu , make the box bigger - avoids triggering on restart
  ## restarts generally spike cpu for 2 minutes
  evaluation_periods  = each.value.evaluation_periods
  datapoints_to_alarm = each.value.datapoints_to_alarm
  extended_statistic  = try(each.value.extended_statistic, null) # Optional: can be omitted if not required

  insufficient_data_actions = []
  metric_name               = try(each.value.metric_name, "CPUUtilization")
  namespace                 = try(each.value.namespace, "AWS/ECS")
  ok_actions                = []
  period                    = 60
  statistic                 = "Maximum"
  tags                      = {} # An empty map, as in the original state
  threshold                 = each.value.threshold
  treat_missing_data        = "missing"
  unit                      = null # Optional: can be omitted if not required
}

resource "aws_lambda_permission" "this" {

  for_each = aws_cloudwatch_metric_alarm.this

  statement_id  = "${var.prefix}-${each.value.alarm_name}-invoke"
  action        = "lambda:InvokeFunction"
  function_name = module.lambda__this.lambda_function_name
  # The principal is CloudWatch so that it can invoke the Lambda.
  principal      = "lambda.alarms.cloudwatch.amazonaws.com"
  source_account = data.aws_caller_identity.current.account_id
  ### needed if we start publishing versions of the function
  #   qualifier = aws_lambda_alias.vert-scale-lambda.name

  # Restrict the permission so that only the defined CloudWatch alarm can invoke the function.
  source_arn = each.value.arn
}