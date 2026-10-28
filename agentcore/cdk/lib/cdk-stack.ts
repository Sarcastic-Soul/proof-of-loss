import { AgentCoreApplication, type AgentCoreApplicationProps } from '@aws/agentcore-cdk';
import { CfnOutput, Duration, RemovalPolicy, Stack, type StackProps } from 'aws-cdk-lib';
import * as budgets from 'aws-cdk-lib/aws-budgets';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as s3deploy from 'aws-cdk-lib/aws-s3-deployment';
import { Construct } from 'constructs';
import * as path from 'path';

export interface AgentCoreStackProps extends StackProps {
  /** Props for the AgentCore application, produced by transformAgentCoreJson from agentcore/agentcore.json. */
  application: AgentCoreApplicationProps;
}

// The AgentCore CLI runs the CDK app from agentcore/cdk/.
const REPO_ROOT = path.resolve(process.cwd(), '..', '..');
const BUDGET_EMAIL = 'anishisbusy@gmail.com';
const MONTHLY_BUDGET_USD = 10;

/**
 * Proof of Loss: the agent runtime (from agentcore.json) plus claim storage,
 * a public API in front of the runtime, the web app, and a cost alarm.
 */
export class AgentCoreStack extends Stack {
  public readonly application: AgentCoreApplication;

  constructor(scope: Construct, id: string, props: AgentCoreStackProps) {
    super(scope, id, props);
    this.application = new AgentCoreApplication(this, 'Application', props.application);
    const runtime = this.application.runtime('ProofOfLoss');

    // Photos, claim packets and agent sessions. Demo data, so it expires.
    const data = new s3.Bucket(this, 'Data', {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      removalPolicy: RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      lifecycleRules: [{ expiration: Duration.days(30) }],
      cors: [{
        allowedMethods: [s3.HttpMethods.POST, s3.HttpMethods.GET],
        allowedOrigins: ['*'],
        allowedHeaders: ['*'],
      }],
    });

    const claims = new dynamodb.Table(this, 'Claims', {
      partitionKey: { name: 'claim_id', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: RemovalPolicy.DESTROY,
    });

    runtime.grantReadWrite(data);
    runtime.grantReadWrite(claims);
    runtime.addEnvironmentVariable('POL_BUCKET', data.bucketName);
    runtime.addEnvironmentVariable('POL_TABLE', claims.tableName);

    // Public API: hands out claim ids and upload links, forwards chat turns to the runtime.
    const api = new lambda.Function(this, 'Api', {
      runtime: lambda.Runtime.PYTHON_3_13,
      architecture: lambda.Architecture.ARM_64,
      handler: 'handler.handler',
      code: lambda.Code.fromAsset(path.join(REPO_ROOT, 'api')),
      timeout: Duration.seconds(90),
      memorySize: 256,
      environment: { RUNTIME_ARN: runtime.runtimeArn, BUCKET: data.bucketName },
      logRetention: logs.RetentionDays.ONE_WEEK,
    });
    runtime.grantInvoke(api);
    data.grantPut(api, 'photos/*');
    data.grantRead(api, 'packets/*');
    const apiUrl = api.addFunctionUrl({ authType: lambda.FunctionUrlAuthType.NONE });

    // Web app on a private bucket; CloudFront serves it and routes /api/* to the function,
    // so the browser only ever talks to one origin.
    const site = new s3.Bucket(this, 'Site', {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      removalPolicy: RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    });
    const cdn = new cloudfront.Distribution(this, 'Web', {
      defaultRootObject: 'index.html',
      priceClass: cloudfront.PriceClass.PRICE_CLASS_200,
      defaultBehavior: {
        origin: origins.S3BucketOrigin.withOriginAccessControl(site),
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
      },
      additionalBehaviors: {
        '/api/*': {
          origin: new origins.FunctionUrlOrigin(apiUrl, { readTimeout: Duration.seconds(60) }),
          viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
          allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
          cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
          originRequestPolicy: cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
        },
      },
    });
    new s3deploy.BucketDeployment(this, 'WebFiles', {
      sources: [s3deploy.Source.asset(path.join(REPO_ROOT, 'web'))],
      destinationBucket: site,
      distribution: cdn,
    });

    // Email when the month's actual spend crosses 50% and 100% of the budget.
    new budgets.CfnBudget(this, 'Budget', {
      budget: {
        budgetName: `${this.stackName}-monthly`,
        budgetType: 'COST',
        timeUnit: 'MONTHLY',
        budgetLimit: { amount: MONTHLY_BUDGET_USD, unit: 'USD' },
      },
      notificationsWithSubscribers: [50, 100].map(threshold => ({
        notification: {
          notificationType: 'ACTUAL',
          comparisonOperator: 'GREATER_THAN',
          threshold,
          thresholdType: 'PERCENTAGE',
        },
        subscribers: [{ subscriptionType: 'EMAIL', address: BUDGET_EMAIL }],
      })),
    });

    new CfnOutput(this, 'WebUrl', { value: `https://${cdn.distributionDomainName}` });
    new CfnOutput(this, 'ApiUrl', { value: apiUrl.url });
    new CfnOutput(this, 'DataBucket', { value: data.bucketName });
    new CfnOutput(this, 'ClaimsTable', { value: claims.tableName });
  }
}
