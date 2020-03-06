##################
# App Task Role
######

resource "aws_iam_role" "app_role" {
  name               = "${var.app}-task-role"
  assume_role_policy = data.aws_iam_policy_document.app_role_assume_role_policy.json
  tags               = var.resource_tags
}

resource "aws_iam_role_policy" "app_policy" {
  name   = "${var.app}-policy-role"
  role   = aws_iam_role.app_role.id
  policy = data.aws_iam_policy_document.app_policy.json
}

data "aws_iam_policy_document" "app_policy" {
  statement {
    actions = ["s3:*"]
    resources = [
      "${aws_s3_bucket.website.arn}",
      "${aws_s3_bucket.website.arn}/*"
    ]
  }
}

data "aws_iam_policy_document" "app_role_assume_role_policy" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}


########################
# ECS Agent Exec Role
######

# https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task_execution_IAM_role.html
resource "aws_iam_role" "ecs_task_exec_role" {
  name               = "${var.app}-ecs-exec"
  assume_role_policy = data.aws_iam_policy_document.assume_role_policy.json
  tags               = var.resource_tags
}

# allow task execution role to be assumed by ecs
data "aws_iam_policy_document" "assume_role_policy" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# allow task execution role to work with ecr and cw logs
resource "aws_iam_role_policy_attachment" "ecsTaskExecutionRole_policy" {
  role       = aws_iam_role.ecs_task_exec_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

########################
# CWE Role
######
# https://docs.aws.amazon.com/AmazonECS/latest/developerguide/CWE_IAM_role.html
#
resource "aws_iam_role" "cloudwatch_events_role" {
  name               = "${var.app}-events"
  assume_role_policy = data.aws_iam_policy_document.events_assume_role_policy.json
  tags               = var.resource_tags
}


# allow events role to be assumed by events service 
data "aws_iam_policy_document" "events_assume_role_policy" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
  }
}

# allow events role to run ecs tasks
data "aws_iam_policy_document" "events_ecs" {
  statement {
    effect    = "Allow"
    actions   = ["ecs:RunTask"]
    resources = ["arn:aws:ecs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:task-definition/${aws_ecs_task_definition.app.family}:*"]

    condition {
      test     = "StringLike"
      variable = "ecs:cluster"
      values   = [aws_ecs_cluster.app.arn]
    }
  }
}

resource "aws_iam_role_policy" "events_ecs" {
  name   = "${var.app}-events-ecs"
  role   = aws_iam_role.cloudwatch_events_role.id
  policy = data.aws_iam_policy_document.events_ecs.json
}


# allow events role to pass role to task execution role and app role
data "aws_iam_policy_document" "passrole" {
  statement {
    effect  = "Allow"
    actions = ["iam:PassRole"]

    resources = [
      aws_iam_role.app_role.arn,
      aws_iam_role.ecs_task_exec_role.arn,
    ]
  }
}

resource "aws_iam_role_policy" "events_ecs_passrole" {
  name   = "${var.app}-events-ecs-passrole"
  role   = aws_iam_role.cloudwatch_events_role.id
  policy = data.aws_iam_policy_document.passrole.json
}
