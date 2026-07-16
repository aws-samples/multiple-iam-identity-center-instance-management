# Regional Routing with Custom Vanity Domains for IAM Identity Center

This solution deploys a custom vanity domain (e.g., `aws.mycompany.com`) that serves as a single, memorable entry point for IAM Identity Center access portals across multiple AWS Regions. It uses latency-based routing to automatically redirect users to their nearest healthy access portal endpoint and provides automated failover when a Region is impaired.

> **Full walkthrough:** For detailed step-by-step instructions including console-based deployment, 
> see the [accompanying blog post](https://aws.amazon.com/blogs/security/regional-routing-for-aws-access-portals-implementing-custom-vanity-domains-for-iam-identity-center/).
> This README covers infrastructure-as-code deployment using the provided CloudFormation templates.

## Architecture

![Regional routing architecture for IAM Identity Center vanity domains](regional-routing/architecture.png)


**Components:**
- **Amazon Route 53** — Latency-based routing and health checks
- **AWS Certificate Manager (ACM)** — TLS certificates with automatic renewal
- **Application Load Balancer (ALB)** — 302 redirects to Regional access portal endpoints
- **Amazon Application Recovery Controller (ARC)** — Managed Regional failover (Phase 3)

**Flow:**
1. User (via browser or AWS CLI) resolves `aws.mycompany.com`
2. Route 53 evaluates latency records and routes to the nearest healthy ALB
3. ALB terminates TLS (using ACM certificate) and issues a 302 redirect to the Regional Identity Center access portal
4. ARC controls health check states — when a Region is deactivated, Route 53 stops routing traffic to it

## Phases

The solution is structured in three progressive phases. Deploy each phase independently based on your needs:

| Phase | Description | Requires |
|-------|-------------|----------|
| **Phase 1** | Single-Region vanity domain redirect | One Identity Center Region |
| **Phase 2** | Multi-Region latency-based routing | Identity Center multi-Region replication |
| **Phase 3** | ARC Region switch for managed failover | Phase 2 + ARC |

## Prerequisites

1. An existing top-level domain (e.g., `mycompany.com`)
2. An [AWS IAM Identity Center organization instance](https://docs.aws.amazon.com/singlesignon/latest/userguide/identity-center-instances.html) configured
3. For Phases 2 and 3: IAM Identity Center [multi-Region replication](https://docs.aws.amazon.com/singlesignon/latest/userguide/multi-region-iam-identity-center.html) with at least two Regions
4. IAM permissions to manage Route 53, ACM, EC2/ALB, and ARC
>You do NOT need an existing VPC. Each template creates a lightweight dual-stack VPC with public subnets by default. If you prefer to use your own, fill in the optional VPC/subnet/security group variables in `deploy.sh`.

## Deployment

### Option 1: Deploy individual phases

Download and deploy each CloudFormation template individually:

```bash
# Phase 1 – Single-Region redirect
aws cloudformation create-stack \
  --stack-name idc-vanity-phase1 \
  --template-body file://phase1-single-region-redirect.yaml \
  --parameters ParameterKey=VanityDomain,ParameterValue=aws.mycompany.com ...
```
```bash
# Phase 2 – Multi-Region latency (deploy in each additional Region)
aws cloudformation create-stack \
  --stack-name idc-vanity-phase2 \
  --template-body file://phase2-multi-region-latency.yaml \
  --parameters ...
```
```bash
# Phase 3 – ARC Region switch failover
aws cloudformation create-stack \
  --stack-name idc-vanity-phase3 \
  --template-body file://phase3-arc-region-switch.yaml \
  --parameters ...
```

### Option 2: Deploy all phases with a single script

1. Open deploy.sh and update the required parameters:
```
TLD="mycompany.com"
TLD_HOSTED_ZONE_ID="Z0123456789EXAMPLE"
IDC_SUBDOMAIN="aws"
IDC_INSTANCE_ID="ssoins-1234567890"
PRIMARY_REGION="us-east-2"
ADDITIONAL_REGIONS="us-west-2"
```

2. Run the deployment:

```bash
./deploy.sh
```

The script deploys all three phases in sequence and creates the necessary infrastructure across your primary and additional Regions.

## Configuration Reference

### deploy.sh variables

| Variable | Required | Description |
|---|---|---|
| `TLD` | Yes | Your top-level domain (e.g. `mycompany.com`) |
| `TLD_HOSTED_ZONE_ID` | Yes | Route 53 hosted zone ID for your TLD |
| `IDC_SUBDOMAIN` | Yes | Subdomain prefix only, without the TLD (e.g. `aws`) |
| `IDC_INSTANCE_ID` | Yes | Your Identity Center instance ID |
| `PRIMARY_REGION` | Yes | AWS region for Phase 1 (default: `us-east-1`) |
| `ADDITIONAL_REGIONS` | No | Bash array of AWS regions for Phase 2; leave empty `()` to skip Phase 2 |
| `DEPLOY_PHASE3` | No | Set to `"true"` to deploy Phase 3, anything else skips it |
| `ARC_FAILOVER_REGION` | No | The single failover region for the ARC plan; defaults to `ADDITIONAL_REGIONS[0]` if empty. ARC supports exactly 2 regions per plan |
| `ARC_EXECUTION_ROLE_ARN` | No | Existing IAM role ARN for ARC; auto-created if empty |
| `P1_VPC_ID` / `P2_VPC_ID` | No | Existing VPC ID per phase; auto-created if empty |
| `P1_SUBNET_IDS` / `P2_SUBNET_IDS` | No | Comma-separated public subnet IDs; auto-created if empty |
| `P1_SECURITY_GROUP_ID` / `P2_SECURITY_GROUP_ID` | No | Existing security group ID; auto-created if empty |


## Validation

After deployment, verify the redirect is working:
```bash
curl -I https://aws.mycompany.com
```

Expected response:
```bash
HTTP/2 302
location: https://ssoins-1234567890.portal.us-east-2.app.aws
```
## Triggering a Failover

After Phase 3 is deployed, use the ARC plan ARN from the script output (or from the Phase 3 stack outputs) to shift traffic.

**Deactivate a region** (shift traffic away):

```bash
aws arc-region-switch start-plan-execution \
  --plan-arn <ArcPlanArn output from your stack> \
  --target-region us-west-2 \          # must be Region1 or Region2 from your stack
  --action deactivate \
  --comment "Deactivating us-west-2 for maintenance" \
  --region us-east-2                   # region where the CloudFormation stack was deployed
```

**Re-activate a region** (restore normal routing):

```bash
aws arc-region-switch start-plan-execution \
  --plan-arn <ARC_PLAN_ARN> \
  --target-region us-west-2  \
  --action activate \
  --comment "Re-activating us-west-2" \
  --region us-east-1
```
## AWS CLI Support

The AWS CLI (v2.35.13+) supports vanity domains as an sso_start_url value. After deploying this solution:
```bash
aws configure sso
# When prompted for SSO start URL, enter: https://aws.mycompany.com
```

The CLI resolves the vanity domain to determine the Regional Identity Center endpoint automatically. For multi-Region deployments, the CLI benefits from the same latency-based routing and failover behavior as browser-based access.

## Things to Know

-  Use 302 (Found) status codes, not 301. A 301 causes browsers to cache the redirect, preventing failovers from working until the cache expires.
- The vanity domain does not appear in the browser's address bar — users are redirected to the Regional access portal URL.
- DNS propagation for NS delegation can take up to 48 hours, though it typically completes within minutes for Route 53-to-Route 53 delegation.
- ALB listeners use **302 (Found)** redirects, not 301. Using 301 causes browsers to cache the redirect and breaks failover.
- HTTPS listeners use the `ELBSecurityPolicy-TLS13-1-2-Res-FIPS-PQ-2025-09` TLS policy.
- Phase 2 ALBs have deletion protection enabled by default. Phase 1 does not.
- The script uses `aws cloudformation deploy`, which handles both create and update — safe to re-run.
- Adding a new region later? Add it to the `ADDITIONAL_REGIONS` array and re-run the script. The ARC plan will automatically pick it up if `DEPLOY_PHASE3="true"` and `ARC_FAILOVER_REGION` is empty — but note ARC supports only 2 regions per plan, so only `ADDITIONAL_REGIONS[0]` is used as the failover. Set `ARC_FAILOVER_REGION` explicitly if you want a different region to be the failover target.
- The Phase 3 template supports exactly 2 regions per ARC plan. If you need to fail over to a third region, you would need a second ARC plan.



## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This library is licensed under the MIT-0 License. See the LICENSE file.

