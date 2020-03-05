resource "aws_ecr_repository" "registry" {
  name                 = var.app
  image_tag_mutability = "MUTABLE"
  tags                 = var.resource_tags
  image_scanning_configuration {
    scan_on_push = true
  }
}
