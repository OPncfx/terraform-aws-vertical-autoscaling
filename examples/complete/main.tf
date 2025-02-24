module "vertical_autoscale" {
  source = "../../"
  prefix = "vertical-autoscale"
    description = "Scale up containers when alarm triggered"
    tags = {
    Name = "vertical-autoscale-lambda"
    }
    metrics = [
    {
      name = "CPUUtilization"
      alarm_name = "ecs_service_cpu_alarm"
      alarm_description = "Crypto Websocket Ingester has peaked above 90% CPU"
      metric_name = "CPUUtilization"
      namespace = "AWS/ECS"
      evaluation_periods = 5
      datapoints_to_alarm = 4
      extended_statistic = null
      threshold = 90
      cluster_name = ""
      service_name = ""
    }
    ]
}