resource "aws_cognito_user_pool" "this" {
  name = "${var.name_prefix}-${var.env}"

  password_policy {
    minimum_length    = 12
    require_lowercase = true
    require_uppercase = true
    require_numbers   = true
    require_symbols   = true
  }

  auto_verified_attributes = ["email"]
}

# Shared by AppSync (as its Cognito auth provider) and the React app's login flow.
resource "aws_cognito_user_pool_client" "app" {
  name         = "${var.name_prefix}-${var.env}-dashboard"
  user_pool_id = aws_cognito_user_pool.this.id

  generate_secret     = false
  explicit_auth_flows = ["ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH", "ALLOW_USER_SRP_AUTH"]
}
