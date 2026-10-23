# Managing Multiple IAM Identity Center Instances

This repository provides solutions for organizations managing IAM Identity Center at scale — whether operating multiple instances across member accounts, routing users across Regions, or extending workforce account access beyond Identity Center permission sets.

## Solutions

1. Instance Visibility & Reporting

Deploys an AWS Lambda function that scans your organization, identifies all Identity Center instances, detects duplicated users across instances, and generates reports on application assignments.

→ [View solution](instance-reporting/README.md)

2. Regional Routing with Custom Vanity Domains

Provides CloudFormation templates to deploy a custom vanity domain (e.g., aws.mycompany.com) that routes users to the nearest healthy IAM Identity Center access portal endpoint using latency-based routing, with failover via Amazon Application Recovery Controller (ARC).

    Phase 1: Single-Region redirect
    Phase 2: Multi-Region latency-based routing
    Phase 3: ARC Region Switch for managed failover

→ [View solution](regional-routing/README.md)

3. AWS CLI Integration for IAM Account Access Manager

Provides Python scripts that let your workforce use the AWS CLI with roles assigned through IAM Account Access Manager — the account access portal that assigns IAM roles to users across accounts while IAM Identity Center manages the login session. The scripts configure named CLI profiles with automatic credential refresh, so `aws` commands work normally until the Identity Center session expires, the same way `aws sso login` already works for permission sets.

→ [View solution](IAM-account-access-cli/README.md)

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This library is licensed under the MIT-0 License. See the LICENSE file.

