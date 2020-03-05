
resource "aws_ecs_task_definition" "app" {
  family                   = var.app
  container_definitions    = templatefile(
    "task-definitions/sitebuild.json", {
      image = "${aws_ecr_repository.registry.repository_url}:latest",
      log_group = "/fargate/tasks/${var.app}",
      region = data.aws_region.current.name})
      
  network_mode             = "awsvpc"
  execution_role_arn       = aws_iam_role.ecs_task_exec_role.arn
  task_role_arn            = aws_iam_role.app_role.arn
  cpu                      = 512
  memory                   = 1024
  requires_compatibilities = ["FARGATE"]
  tags                     = var.resource_tags

  volume {
    name = "work_dir"
  }

}

variable "logs_retention_in_days" {
  type        = number
  default     = 90
  description = "Specifies the number of days you want to retain log events"
}

resource "aws_cloudwatch_log_group" "logs" {
  name = "/fargate/tasks/${var.app}"
  retention_in_days = 90
  tags = var.resource_tags
}
