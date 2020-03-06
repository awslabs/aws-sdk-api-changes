variable "schedule_expression" {
  type    = string
  default = "rate(6 hours)"
}

resource "aws_cloudwatch_event_rule" "scheduled_build" {
  name                = "${var.app}-build"
  description         = "Runs fargate task ${var.app}: ${var.schedule_expression}"
  schedule_expression = var.schedule_expression
  tags                = var.resource_tags
}

resource "aws_cloudwatch_event_target" "scheduled_build" {
  rule      = aws_cloudwatch_event_rule.scheduled_build.name
  target_id = "${var.app}-build-target"
  arn       = aws_ecs_cluster.app.arn
  role_arn  = aws_iam_role.cloudwatch_events_role.arn
  input     = "{}"

  ecs_target {
    task_count          = 1
    task_definition_arn = aws_ecs_task_definition.app.arn
    launch_type         = "FARGATE"
    platform_version    = "LATEST"

    network_configuration {
      assign_public_ip = true
      security_groups  = [aws_security_group.nsg_task.id]
      subnets          = split(",", var.subnets)
    }
  }
}
