# AWS CLI Integration for IAM Account Access Manager

## What is this?

AWS IAM Account Access Manager (AAM) is a workforce account access portal that
lets your organization assign IAM roles to users across multiple AWS accounts.
It uses IAM Identity Center for authentication, but manages
its own separate set of access assignments, independent of the Identity Center
Access Portal.

The AWS CLI does not natively support Account Access Manager yet. These scripts
bridge that gap. They configure your CLI to authenticate through AAM, discover
your assigned roles, and set up named profiles so you can use `aws` commands
normally; with automatic credential refresh; until your Identity Center
session expires.

**You do not need to manage credentials manually.** Once set up, the CLI
handles everything in the background; as long as these scripts remain in the
same location where you ran the setup.

---

## How it works

There are four scripts. You only need to run three of them:

| Script | What it does | Run it? |
|---|---|---|
| `configure-account-access.py` | Writes your AAM session config to `~/.aws/config` and opens the browser for login | Once, at setup |
| `list-roles.py` | Fetches all IAM roles you have access to through AAM | At setup, or to refresh role list |
| `create-profiles.py` | Creates AWS CLI profiles for each role | At setup, or to add new profiles |
| `refresh-credentials.py` | Fetches short-lived credentials for a profile on demand | **Never — the CLI calls this automatically** |
| `setup.py` | Runs all of the above in one command | [Reference implementation — see note](#quick-start--setuppy) |

### About `refresh-credentials.py`

You never call this script directly. When `create-profiles.py` or `setup.py`
creates a profile in `~/.aws/config`, it wires up a `credential_process` entry
that points the AWS CLI at `refresh-credentials.py`. Every time you run an
`aws` command with one of these profiles, the CLI silently calls this script in
the background to get fresh credentials.

**Important:** these scripts must stay in the same directory after setup.
The path written into `~/.aws/config` is the absolute path to
`refresh-credentials.py` at the time you ran setup. If you move the folder
afterward, credential refresh will fail. To fix it, re-run `setup.py` (or
`create-profiles.py`) from the new location; existing profiles with the old
path will be skipped, but you can remove them from `~/.aws/config` manually
and re-run to recreate them.

### Resilience at scale

The role-listing logic in `list-roles.py` and `setup.py` is designed to handle
large numbers of roles reliably:

- **Pagination** — roles are fetched one page at a time using a `nextToken`
  cursor. The scripts loop until the API returns `nextToken: null`, so there
  is no limit on the total number of roles supported.
- **Connection drop handling and retries** — both scripts use a `requests.Session`
  with a `HTTPAdapter` configured for automatic retries. If the connection drops
  or the server returns a 5xx error, the session transparently reconnects and
  retries with exponential backoff — no manual connection management needed.
- **Socket timeout** — each request has a 30-second timeout. If the server
  stops responding, the script fails fast and retries rather than hanging
  indefinitely.
- **Retry limit** — after 5 consecutive failures, the script exits with an
  error rather than retrying forever.

---

## Prerequisites

- Requires Python 3.9+ (tested on 3.12)
  - `botocore` — `pip install botocore`
  - `python-dateutil` — `pip install python-dateutil`
  - `requests` — `pip install requests`
- AWS CLI v2

Or install all dependencies at once:

```bash
pip install -r requirements.txt
```

The examples below assume your shell is in the same directory as these scripts.
If you placed them elsewhere, substitute that path.

---

## Quick start — `setup.py`

> **Note:** `setup.py` is a reference implementation intended to show how the
> full setup flow fits together. Use it as a guide to build your own onboarding
> script tailored to your environment; do not deploy it to production as-is.

For most users exploring AAM, `setup.py` is the fastest way to get started.

```bash
python setup.py \
    --sso-start-url https://d-aaabbb1111.awsapps.com/start \
    --sso-region us-west-2 \
    --account-access-url https://aa-a1b2c3d4f5.account-access.us-west-2.app.aws
```

Run without flags to be prompted interactively:

```bash
python setup.py
```

### Profile naming

By default, profiles are named `{role}-{account}`, for example
`ReadOnlyAccess-123456789012`. Use `--profile-format` to change this.

| Token | Value |
|---|---|
| `{prefix}` | Literal string from `--prefix` (default: `aws`) |
| `{account}` | 12-digit AWS account ID |
| `{role}` | Role name (last segment of the role ARN) |
| `{path}` | IAM role path segments, e.g. `prod/payments` from `role/prod/payments/ReadOnlyAccess`. Empty string if the role has no path. |

```bash
# Produces profiles like: aws-123456789012-ReadOnlyAccess
python setup.py \
    --sso-start-url https://d-aaabbb1111.awsapps.com/start \
    --sso-region us-west-2 \
    --account-access-url https://aa-a1b2c3d4f5.account-access.us-west-2.app.aws \
    --profile-format "{prefix}-{account}-{role}" \
    --prefix aws
```

After setup, use your profiles normally:

```bash
aws sts get-caller-identity --profile aws-123456789012-ReadOnlyAccess
```

See `python setup.py --help` for all options.

---

## Step-by-step setup

Use the individual scripts if you want more control; for example to filter
which roles get profiles, or to use a different format for each step.

### Step 1 — Configure your session

```bash
python configure-account-access.py \
    --sso-start-url https://d-aaabbb1111.awsapps.com/start \
    --sso-region us-west-2 \
    --account-access-url https://aa-a1b2c3d4f5.account-access.us-west-2.app.aws
```

This writes an `[sso-session]` block to `~/.aws/config` and immediately opens
the browser for your first login. You only need to run this once per Identity
Center user. If a session with that name already exists, the script exits
without modifying your config.

Use `--sso-session` to give the session a custom name (default:
`account-access-session`). Pass that same name to every subsequent command.

### Step 2 — List your roles

```bash
python list-roles.py
python list-roles.py --output csv > roles.csv
python list-roles.py --sso-session <custom-session-name>
```

Prints every IAM role you have access to through AAM as a JSON array (default)
or CSV. You can pipe this directly into `create-profiles.py`, save it to a
file, or filter it first.

### Step 3 — Create profiles

```bash
# All roles, from stdin
python list-roles.py | python create-profiles.py

# Filtered — ReadOnly roles only
python list-roles.py | jq 'map(select(.roleArn | contains("ReadOnly")))' | python create-profiles.py

# From a saved file
python create-profiles.py --from-file roles.json
python create-profiles.py --from-file roles.csv --input csv

# If using a custom session name
python create-profiles.py --sso-session <custom-session-name>
```

Creates an AWS CLI profile in `~/.aws/config` for each role. Profiles that
already exist are skipped. The script prints a summary of what was created and
what was skipped.

You can optionally add `profileName` and `sessionName` fields to the input data
to override the defaults for individual roles.

### Step 4 — Use the AWS CLI

```bash
aws sts get-caller-identity --profile <profile-name>
aws s3 ls --profile <profile-name>
```

Credentials are fetched and refreshed automatically. When your Identity Center
session expires, log back in with:

```bash
aws sso login --sso-session account-access-session
```

---

## Full example

Configure, list, filter to ReadOnly roles only, create profiles, and verify:

```bash
python configure-account-access.py \
    --sso-session session-for-reading \
    --sso-start-url https://d-abcde01234.awsapps.com/start \
    --sso-region us-west-2 \
    --account-access-url https://aa-ab0cde1f2.account-access.us-west-2.app.aws

python list-roles.py --sso-session session-for-reading --output json \
    | jq 'map(select(.roleArn | contains("ReadOnly")))' \
    | python create-profiles.py --sso-session session-for-reading

aws sts get-caller-identity --profile ReadOnlyAccess-123456123456
```
