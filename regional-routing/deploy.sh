#!/usr/bin/env bash
# =============================================================================
# IDC Vanity Domain - Orchestrated Deployment
# Deploys all three phases in sequence, automatically wiring outputs between them.
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration — edit these values before running
# ---------------------------------------------------------------------------
TLD="swisscomms.com"
TLD_HOSTED_ZONE_ID="Z08558301HIVUL92TCFDS"
IDC_SUBDOMAIN="corp" # Set to only the subdomain name without the TLD
IDC_INSTANCE_ID="ssoins-72236207e261e9df"

PRIMARY_REGION="us-east-1"
ADDITIONAL_REGIONS=(
  "eu-central-1"
  # "ap-southeast-1"
)
# Leave the array empty () to skip Phase 2

# Phase 3 (ARC failover) — set to "false" to skip
# NOTE: ARC Region Switch plans support exactly 2 regions (primary + one failover).
# Region2 defaults to the first entry in ADDITIONAL_REGIONS if left empty.
DEPLOY_PHASE3="true"
ARC_FAILOVER_REGION=""          # Explicit failover region; auto-set from ADDITIONAL_REGIONS[0] if empty
ARC_EXECUTION_ROLE_ARN=""       # Leave empty to auto-create

# Optional: bring-your-own VPC (leave empty to auto-create)
P1_VPC_ID=""
P1_SUBNET_IDS=""
P1_SECURITY_GROUP_ID=""

P2_VPC_ID=""
P2_SUBNET_IDS=""
P2_SECURITY_GROUP_ID=""

# Stack names
P1_STACK="idc-vanity-phase1"
P3_STACK="idc-vanity-phase3"
# ---------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CFN_DIR="${SCRIPT_DIR}"

echo "============================================================"
echo " IDC Vanity Domain — Orchestrated Deployment"
echo "============================================================"

# ---- Phase 1 ---------------------------------------------------------------
echo ""
echo "[Phase 1] Deploying to primary region: ${PRIMARY_REGION}"

aws cloudformation deploy \
  --template-file "${CFN_DIR}/phase1-single-region-redirect.yaml" \
  --stack-name "${P1_STACK}" \
  --region "${PRIMARY_REGION}" \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    TLD="${TLD}" \
    TLDHostedZoneId="${TLD_HOSTED_ZONE_ID}" \
    IdentityCenterSubdomain="${IDC_SUBDOMAIN}" \
    IdentityCenterInstanceId="${IDC_INSTANCE_ID}" \
    VpcId="${P1_VPC_ID}" \
    SubnetIds="${P1_SUBNET_IDS}" \
    SecurityGroupId="${P1_SECURITY_GROUP_ID}"

echo "[Phase 1] Complete. Fetching outputs..."

GLOBAL_HOSTED_ZONE_ID=$(aws cloudformation describe-stacks \
  --stack-name "${P1_STACK}" \
  --region "${PRIMARY_REGION}" \
  --query "Stacks[0].Outputs[?OutputKey=='GlobalHostedZoneId'].OutputValue" \
  --output text)

GLOBAL_DOMAIN_NAME=$(aws cloudformation describe-stacks \
  --stack-name "${P1_STACK}" \
  --region "${PRIMARY_REGION}" \
  --query "Stacks[0].Outputs[?OutputKey=='GlobalDomainName'].OutputValue" \
  --output text)

echo "  GlobalHostedZoneId : ${GLOBAL_HOSTED_ZONE_ID}"
echo "  GlobalDomainName   : ${GLOBAL_DOMAIN_NAME}"

# ---- Phase 2 ---------------------------------------------------------------
if [[ ${#ADDITIONAL_REGIONS[@]} -gt 0 ]]; then
  for ADDITIONAL_REGION in "${ADDITIONAL_REGIONS[@]}"; do
    echo ""
    echo "[Phase 2] Deploying additional region: ${ADDITIONAL_REGION}"

    aws cloudformation deploy \
      --template-file "${CFN_DIR}/phase2-multi-region-latency.yaml" \
      --stack-name "idc-vanity-phase2-${ADDITIONAL_REGION}" \
      --region "${ADDITIONAL_REGION}" \
      --parameter-overrides \
        IdentityCenterInstanceId="${IDC_INSTANCE_ID}" \
        GlobalHostedZoneId="${GLOBAL_HOSTED_ZONE_ID}" \
        GlobalDomainName="${GLOBAL_DOMAIN_NAME}" \
        VpcId="${P2_VPC_ID}" \
        SubnetIds="${P2_SUBNET_IDS}" \
        SecurityGroupId="${P2_SECURITY_GROUP_ID}"

    echo "[Phase 2] Complete for ${ADDITIONAL_REGION}."
  done
else
  echo ""
  echo "[Phase 2] Skipped (ADDITIONAL_REGIONS is empty)."
fi

# ---- Phase 3 ---------------------------------------------------------------
if [[ "${DEPLOY_PHASE3}" == "true" ]]; then
  echo ""
  echo "[Phase 3] Deploying ARC failover plan to: ${PRIMARY_REGION}"

  # ARC Region Switch supports exactly 2 regions: primary + one failover.
  REGION1="${PRIMARY_REGION}"

  # Use explicit failover region if set, otherwise fall back to first additional region.
  if [[ -n "${ARC_FAILOVER_REGION}" ]]; then
    REGION2="${ARC_FAILOVER_REGION}"
  elif [[ ${#ADDITIONAL_REGIONS[@]} -gt 0 ]]; then
    REGION2="${ADDITIONAL_REGIONS[0]}"
  else
    echo "[Phase 3] ERROR: ARC requires a failover region. Set ARC_FAILOVER_REGION or add at least one entry to ADDITIONAL_REGIONS."
    exit 1
  fi

  echo "  ARC Region1 (primary)  : ${REGION1}"
  echo "  ARC Region2 (failover) : ${REGION2}"

  aws cloudformation deploy \
    --template-file "${CFN_DIR}/phase3-arc-region-switch.yaml" \
    --stack-name "${P3_STACK}" \
    --region "${PRIMARY_REGION}" \
    --capabilities CAPABILITY_NAMED_IAM \
    --parameter-overrides \
      GlobalHostedZoneId="${GLOBAL_HOSTED_ZONE_ID}" \
      GlobalDomainName="${GLOBAL_DOMAIN_NAME}" \
      Region1="${REGION1}" \
      Region2="${REGION2}" \
      ArcExecutionRoleArn="${ARC_EXECUTION_ROLE_ARN}"

  ARC_PLAN_ARN=$(aws cloudformation describe-stacks \
    --stack-name "${P3_STACK}" \
    --region "${PRIMARY_REGION}" \
    --query "Stacks[0].Outputs[?OutputKey=='ArcPlanArn'].OutputValue" \
    --output text)

  echo "[Phase 3] Complete."
  echo "  ARC Plan ARN: ${ARC_PLAN_ARN}"
else
  echo ""
  echo "[Phase 3] Skipped (DEPLOY_PHASE3 is not 'true')."
fi

echo ""
echo "============================================================"
echo " Deployment complete!"
echo " Vanity domain: https://${GLOBAL_DOMAIN_NAME:-${IDC_SUBDOMAIN}.${TLD}}"
echo "============================================================"
