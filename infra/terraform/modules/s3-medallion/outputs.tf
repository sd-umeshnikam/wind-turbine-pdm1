output "bucket_names" {
  description = "Map of layer (bronze/silver/gold) to bucket name."
  value       = { for layer, bucket in aws_s3_bucket.this : layer => bucket.bucket }
}

output "bucket_arns" {
  description = "Map of layer (bronze/silver/gold) to bucket ARN."
  value       = { for layer, bucket in aws_s3_bucket.this : layer => bucket.arn }
}

output "bronze_bucket_name" {
  value = aws_s3_bucket.this["bronze"].bucket
}

output "bronze_bucket_arn" {
  value = aws_s3_bucket.this["bronze"].arn
}

output "silver_bucket_name" {
  value = aws_s3_bucket.this["silver"].bucket
}

output "silver_bucket_arn" {
  value = aws_s3_bucket.this["silver"].arn
}

output "gold_bucket_name" {
  value = aws_s3_bucket.this["gold"].bucket
}

output "gold_bucket_arn" {
  value = aws_s3_bucket.this["gold"].arn
}
