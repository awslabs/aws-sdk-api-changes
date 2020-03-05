resource "aws_ecs_cluster" "app" {
  name               = var.app
  tags               = var.resource_tags
  capacity_providers = ["FARGATE_SPOT", "FARGATE"]

  default_capacity_provider_strategy {
    capacity_provider = "FARGATE_SPOT"
    weight = 100
  }
}
