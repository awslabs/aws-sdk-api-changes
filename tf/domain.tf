
data "aws_route53_zone" "zone" {
  name = var.domain
}


resource "aws_route53_record" "bucket" {
  zone_id = data.aws_route53_zone.zone.id
  name    = var.domain
  type    = "A"

  alias {
    name                   = aws_cloudfront_distribution.www_distribution.domain_name
    zone_id                = aws_cloudfront_distribution.www_distribution.hosted_zone_id
    evaluate_target_health = false
    #    name    = aws_s3_bucket.website.website_domain
    #    zone_id = aws_s3_bucket.website.hosted_zone_id
  }
}


