variable "app" {
  type    = string
  default = "apichanges"
}

variable "vpc" {
  type    = string
}

variable "resource_tags" {
  type = map
  default = {
    "App" = "AWSAPIChanges"
  }
}

variable "domain" {
  type    = string
}

variable "access_log_bucket" {
  type    = string
}

variable "subnets" {
  type = string
}
