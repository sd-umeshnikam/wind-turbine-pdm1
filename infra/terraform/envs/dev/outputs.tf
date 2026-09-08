output "graphql_url" {
  value = module.appsync_api.graphql_url
}

output "realtime_url" {
  value = module.appsync_api.realtime_url
}

output "cloudfront_domain_name" {
  value = module.cloudfront_spa.distribution_domain_name
}

output "cognito_user_pool_id" {
  value = module.cognito.user_pool_id
}

output "cognito_app_client_id" {
  value = module.cognito.app_client_id
}

output "databricks_catalog_name" {
  value = module.databricks_unity.catalog_name
}
