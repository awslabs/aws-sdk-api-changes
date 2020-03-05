resource "aws_s3_bucket" "website" {
  bucket = var.domain
  acl    = "public-read"
  policy = templatefile("bucket_policy.json", { domain = var.domain })
  tags   = var.resource_tags
  region = "us-east-1"

  website {
    index_document = "index.html"
    error_document = "error.html"
  }

}
