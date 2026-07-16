# Managing Multiple IAM Identity Center Instances

This repository provides solutions for organizations operating multiple IAM Identity Center instances, whether account-level instances across member accounts, or organization instances replicated across multiple AWS Regions.

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

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This library is licensed under the MIT-0 License. See the LICENSE file.

