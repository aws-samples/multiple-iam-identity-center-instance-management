import argparse
import json
import boto3
import logging
import datetime
import csv
import os

accounts_and_instances_dict={}
duplicated_users ={}

main_session = boto3.session.Session()
sso_admin_client = main_session.client('sso-admin')
identity_store_client = main_session.client('identitystore')
organizations_client = main_session.client('organizations')
s3_client = boto3.client('s3')
logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    application_assignment = []
    user_dict={}
    
    current_account = os.environ['CurrentAccountId']
 
    logger.info("Current account %s", current_account)
    
    paginator = organizations_client.get_paginator('list_accounts')
    page_iterator = paginator.paginate()
    for page in page_iterator:
        for account in page['Accounts']:
            get_credentials(account['Id'],current_account)
            #get all instances per account - returns dictionary of instance id and instances ARN per account
            accounts_and_instances_dict = get_accounts_and_instances(account['Id'], current_account)
            user_dict = get_users(accounts_and_instances_dict[account['Id']][0],user_dict)
            application_assignment = get_application_assignment(accounts_and_instances_dict[account['Id']][1],application_assignment)

    construct_summary(application_assignment, accounts_and_instances_dict, duplicated_users)



                    
def get_accounts_and_instances(account_id, current_account):
    global accounts_and_instances_dict
    
    instance_paginator = sso_admin_client.get_paginator('list_instances')
    instance_page_iterator = instance_paginator.paginate()
    for page in instance_page_iterator:
        for instance in page['Instances']:
            #send back all instances and identity centers
            if account_id == current_account:
                accounts_and_instances_dict = {current_account:[instance['IdentityStoreId'],instance['InstanceArn']]}
            elif instance['OwnerAccountId'] != current_account: 
                accounts_and_instances_dict[account_id]= ([instance['IdentityStoreId'],instance['InstanceArn']])
    return accounts_and_instances_dict
    
#determine if the member IdentityStores have duplicate and update the dictionary
def get_users(identityStoreId, user_dict): 
    global duplicated_users
    paginator = identity_store_client.get_paginator('list_users')
    page_iterator = paginator.paginate(IdentityStoreId=identityStoreId)
    for page in page_iterator:
        for user in page['Users']:
            if ( 'Emails' not in user ):
                print("user has no email")
            else:
                for email in user['Emails']:
                    if email['Value'] not in user_dict:
                        user_dict[email['Value']] = identityStoreId
                    else:
                        print("Duplicate user found " + user['UserName'])
                        user_dict[email['Value']] = user_dict[email['Value']] + "," + identityStoreId
                        duplicated_users[email['Value']] = user_dict[email['Value']]
    return user_dict
    

def get_credentials(account_id,current_account):
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    global sso_admin_client
    global identity_store_client
    role_name = os.environ['CrossAccountRoleName']
    #for mgmt/delegated admin account use the current session
    # for all other accounts assume role into the account and use the assumed role session
    if account_id == current_account :
        sso_admin_client = main_session.client('sso-admin')
        identity_store_client = main_session.client('identitystore')
    else:
        role_arn = f"arn:aws:iam::{account_id}:role/{role_name}"
        logger.info("Switching to %s", role_arn)
        sts = main_session.client('sts')
        assume_role_response = sts.assume_role(
        RoleArn=role_arn, RoleSessionName="CrossAccountMemberRoleSession")
        sso_admin_client = boto3.client(
            'sso-admin',
            aws_access_key_id=assume_role_response['Credentials']['AccessKeyId'],
            aws_secret_access_key=assume_role_response['Credentials']['SecretAccessKey'],
            aws_session_token=assume_role_response['Credentials']['SessionToken'])
        identity_store_client = boto3.client('identitystore',aws_access_key_id=assume_role_response['Credentials']['AccessKeyId'],
            aws_secret_access_key=assume_role_response['Credentials']['SecretAccessKey'],
            aws_session_token=assume_role_response['Credentials']['SessionToken'])
    
def get_application_assignment(instanceARN, application_assignment):
    applications = sso_admin_client.list_applications(InstanceArn = instanceARN)
    
    for application in applications['Applications']:
        all_assignments = sso_admin_client.list_application_assignments(ApplicationArn = application['ApplicationArn'])
        if not all_assignments['ApplicationAssignments']:
            print("There are no assignments for the application ")
        else:
            application_assignment.append({'Name':application['Name'], 'Application ARN': application['ApplicationArn'], 'Users':[]})
            for item in all_assignments['ApplicationAssignments']:
                application_assignment[len(application_assignment)-1]['Users'].append(item['PrincipalId'])
    return application_assignment
    
def csv_to_S3(logsDic, path):
    #create cvs file that will be uploaded to Amazon s3
    bucket = os.environ['reports_bucket']
    now = datetime.datetime.now()
    LambdaTemp= '/tmp/summary_file.csv'
    
    if path == 'identity_center_instances':
        prefix = 'sample/' + str(now) + '_idc_instances_'+'summary_file.csv'
        fields = ['accountId', 'IdentityCenterInstance', 'Identity Store Arn']
    elif path == 'duplicated_users':
        prefix = 'sample/' + str(now) + '_duplicated_users_'+'summary_file.csv'
        fields = ['User_email', 'IdentityStoreId']
    elif path == 'application_assignment':
        prefix = 'sample/' + str(now) + '_application_assignment_'+'summary_file.csv'
        fields = ['Name', 'Application ARN', 'Users']
    fieldnames = 'summary_file.csv'
    with open (LambdaTemp, "w+") as f:
        writer = csv.DictWriter(f, fieldnames = fields)
        writer.writeheader()
        writer.writerows(logsDic)
        #fix self
    try:
        s3_client.upload_file('/tmp/summary_file.csv', bucket, prefix)
    except Exception as ex:
        self.log_error(f'Error upload file to S3 for idc_instances. Error: {str(ex)}')
        raise

    return ("Return to next summary")

def construct_summary(application_assignment, accounts_and_instances_dict, duplicated_users):
    duplicated_users_summary = []
    identity_center_instances_summary = []
    application_assignment_summary =[]
    for item in duplicated_users:
        duplicated_users_summary.append({'User_email':item, 'IdentityStoreId':duplicated_users[item]})
    csv_to_S3(duplicated_users_summary, 'duplicated_users')
    for item in accounts_and_instances_dict:
        identity_center_instances_summary.append({'accountId':item, 'IdentityCenterInstance':accounts_and_instances_dict[item][0], 'Identity Store Arn':accounts_and_instances_dict[item][1]})
    csv_to_S3(identity_center_instances_summary, 'identity_center_instances')
    for item in application_assignment:
        application_assignment_summary.append({'Name':item['Name'], 'Application ARN':item['Application ARN'],'Users':item['Users']})
    csv_to_S3(application_assignment_summary, 'application_assignment')
    return ("Summary is on s3")


if __name__ == "__main__":
    event = {}
    context = "this is a context"
    lambda_handler(event,context)
