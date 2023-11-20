# Multiple Instance Management Iam Identity Center


Multiple account instances of AWS IAM Identity Center can now be deployed in your AWS organization to support authentication for AWS managed applications, such as Amazon Redshift. This solution generates reports to provide visibility into users across multiple IAM Identity Center instances deployed in your AWS organizations. The solution comprises of a script that generates information to help you manage multiple IAM Identity Center instances. The python script will provide you with the following reports:


1.	**Account instances summary:** a report with the accounts and IAM Identity Center instances deployed in each of them.
2.	**User duplication:** a report of all duplicated users and the IAM iIdentity Center instances they belong to. A duplicated user is one that appears in more than one IAM Identity Center instance. Email compares users.
3.	**Application assignments on local instances:** a report with the users assigned to each application

## Solution Overview
![alt diagram](/RepoDiagram.png)



Once you deploy the solution, the AWS Lambda will do the following:
1.	Gets triggered based on the set cron schedule
2.	Lists all accounts in the AWS Organizations
3.	Get the Organization instance of IAM Identity Center Id
4.	Assume a role in each member account
5.	List Account instance of IAM Identity Center, and capture the Id
6.	List applications assigned to each IAM Identity Center instance
7.	List user assignments to each application
8.	Generates and uploads the reports to the Amazon S3 bucket named idc-report-<StackId>

## How to use this solution?

Scripts and templates are available in the repository. Use them how is more comfortable for you. The suggested procedure is to deploy this script in an AWS Lambda in the account where your IAM Identity Center is managed or in the account assigned as a [Delegated administrator for AWS Organizations](https://docs.aws.amazon.com/organizations/latest/userguide/orgs_delegate_policies.html). 
To successfully deploy this solution you will need a AWS Lambda deployment package, an S3 bucket to upload the package, and an IAM role that can be assumed by Lambda in each member account. For ease of deployment in us-east-1 region, , the lambda package is uploaded to an S3 bucket and configured in the cloudFormation Template. If you wish to deploy this in another region, please upload the lambda package to a bucket of your choice in your region and update the S3Bucket and S3Key properties in the cloudFormation Template.


Follow the steps to get started:


1. **Deploy the CloudFormation template:** 
- There are two CloudFormation templates in this repository, the member-account-role.yaml and the management-account-infrastructure.yaml. 
    - If you do not have a cross account role, you can use the member-account-role.yaml to create one. You can use [CloudFormation StackSets](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/what-is-cfnstacksets.html) to deploy this template across multiple accounts. To deploy this template you will need to input your management or delegated admin account ID.
    - The management-account-infrastructure.yaml file will create resources needed for this solution. To deploy this template you will need to input the name of the S3 bucket where your deployment package is, and the cross account role name. If you used the member-account-role.yaml to create the role, you can leave the default value on the CrossAccountRoleName parameter. 

3.	**Deployment considerations:**
-	Cross account role: The AWS Lambda function needs access to your member accounts, for this you need to provide a cross account role. The permissions needed for lambda are listed on the “Require permissions section of this repo”
-	Create a cross account role for Lambda: If you are using an existing role, make sure that all the permissions needed are included on that role. You can see the permissions in the next section.
-	Once the management-account-infrastructure.yaml finishes deploying the resources, you can trigger your new Lambda and  review the report on the Amazon S3 bucket named idc-report-<StackId>
- The Lambda function is scheduled to be triggered once a day at 12:00 AM UTC. 

## Other Considerations

1.	The Lambda execution role will need:
-	AWS Organizations Read permissions
-	AWS IAM Identity Center Read Permissions
-	Permissions to assume a role in each child account in the organization
-   Permissions to put object on the S3 bucket
2. AWS Lambda cross account role:
- sso:ListInstances
- identitystore:ListUsers
- Assume role policy: Principal: AWS: arn:aws:iam::${ManagementAccountId}:role/lambda-execution-role

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This library is licensed under the MIT-0 License. See the LICENSE file.

