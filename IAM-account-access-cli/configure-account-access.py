import argparse
import configparser
import os
import sys

ACCOUNT_ACCESS_SCOPES = [
    "sso:account:access",
    "account_access:read_only",
    "account_access:assume"
]

OPTIONAL_ARGS = {
    "sso-session": {
        "description": "SSO session name | default [account-access-session]",
        "default": "account-access-session",
    },
    "sso-registration-scopes": {
        "description": "SSO registration scopes | default [sso:account:access,account_access:read_only,account_access:assume]",
        "default": ",".join(ACCOUNT_ACCESS_SCOPES),
    },
}

REQUIRED_ARGS = {
    "sso-start-url": "SSO start URL (Required) | example: https://d-aaabbb1111.awsapps.com/start",
    "sso-region": "SSO region (Required) | example: us-west-2",
    "account-access-url": "Account access portal URL (Required) | example: https://aa-a1b2c3d4f5.account-access.us-west-2.app.aws",
}

parser = argparse.ArgumentParser(
    description="Account Access Session Setup", prog="python configure-account-access.py"
)

for arg, fields in OPTIONAL_ARGS.items():
    parser.add_argument(
        "--" + arg, help=fields["description"], default=fields["default"]
    )

for arg, desc in REQUIRED_ARGS.items():
    parser.add_argument("--" + arg, help=desc)

args = parser.parse_args()

args_map = vars(args)

for arg, desc in {s.replace("-", "_"): d for s, d in REQUIRED_ARGS.items()}.items():
    if args_map[arg.replace("-", "_")] is None:
        args_map[arg] = input(desc + ": ")

config = configparser.ConfigParser()
new_config = configparser.ConfigParser()
config.read(os.path.expanduser("~/.aws/config"))

config_session_section = "sso-session " + args_map["sso_session"]
if config.has_section(config_session_section):
    print("-- Found an existing SSO configuration entry with matching name, exiting")
    sys.exit(
        0
    )  # to preserve existing config, file is opened in append mode, not possible to overwrite existing

new_config.add_section(config_session_section)

new_config[config_session_section]["sso_start_url"] = args_map["sso_start_url"]
new_config[config_session_section]["account_access_url"] = args_map[
    "account_access_url"
]
new_config[config_session_section]["sso_region"] = args_map["sso_region"]
new_config[config_session_section]["sso_registration_scopes"] = args_map[
    "sso_registration_scopes"
]

with open(os.path.expanduser("~/.aws/config"), "a") as configfile:
    configfile.write("\n")
    new_config.write(configfile)

# following line can be removed if immediate browser login is not desired
os.execvp("aws", ["aws", "sso", "login", "--sso-session", args_map["sso_session"]])
