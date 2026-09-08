import { SNSClient, PublishCommand } from "@aws-sdk/client-sns";
import type { Alert } from "./types";

let client: SNSClient | undefined;

function getClient(): SNSClient {
  if (!client) {
    client = new SNSClient({ region: process.env.AWS_REGION });
  }
  return client;
}

export async function publishAlert(alert: Alert): Promise<void> {
  const topicArn = process.env.ALERTS_TOPIC_ARN;
  if (!topicArn) {
    throw new Error("ALERTS_TOPIC_ARN is not configured.");
  }

  await getClient().send(
    new PublishCommand({
      TopicArn: topicArn,
      Subject: `Alert: ${alert.component} on ${alert.turbineId}`,
      Message: alert.message,
      MessageAttributes: {
        severity: { DataType: "String", StringValue: alert.severity },
        turbineId: { DataType: "String", StringValue: alert.turbineId },
      },
    }),
  );
}
