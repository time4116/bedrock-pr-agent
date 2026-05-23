# Security

Bedrock PR Agent is designed to run from a public source repository while keeping runtime credentials and deployment-specific values out of Git.

## Public repository rules

- Do not commit `.env`, local AWS config, GitHub App private keys, webhook secrets, personal access tokens, generated CDK output, or AgentCore local state.
- Store GitHub App credentials in AWS Secrets Manager under `GITHUB_SECRET_NAME`.
- Store deployment-only values such as `AWS_ACCOUNT`, `AWS_DEPLOY_ROLE_ARN`, and `BEDROCK_MODEL_ID` in GitHub Actions secrets or variables.
- Use explicit repository allowlisting with `ALLOWED_REPOS`. Empty allowlists reject all repositories; set `*` only when reviewing every installed repository is intentional.

## GitHub App permissions

The app should request only the permissions required by the active workflow:

- **Contents: read** — fetch pull request files and diffs.
- **Pull requests: read/write** — read pull request metadata.
- **Issues: read/write** — create or update the top-level PR timeline comment, which uses GitHub's issue comments API.
- **Actions: read** — optional, only needed when Terraform or CI log validation is enabled.
- **Metadata: read** — required by GitHub Apps.

After changing GitHub App permissions, the installation owner must approve the updated permissions before new installation tokens include them.

## Deployment credentials

GitHub Actions should assume an AWS role through OIDC. Do not store long-lived AWS access keys in the repository or in workflow files.

The deploy role should be constrained to this repository's `main` branch and to the CDK resources required for deployment. The included `scripts/create_deploy_role.py` follows that pattern.

## Webhook security

The webhook endpoint is public by design, but every request must include a valid GitHub `X-Hub-Signature-256` HMAC signature. Events are also filtered by type, action, repository allowlist, and weekly rate limit before work is queued.

## Reporting issues

Please open a GitHub issue for non-sensitive security concerns. For anything that could expose credentials, account-specific infrastructure, or unauthorized access, contact the repository owner privately before publishing details.
