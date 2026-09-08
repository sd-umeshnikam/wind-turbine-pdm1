import { AwsClient } from "aws4fetch";
import type { TwinState } from "./types";

const MUTATION = /* GraphQL */ `
  mutation PublishTwinUpdate($input: TwinStateInput!) {
    publishTwinUpdate(input: $input) {
      turbineId
    }
  }
`;

let signer: AwsClient | undefined;

function getSigner(): AwsClient {
  if (!signer) {
    signer = new AwsClient({
      accessKeyId: process.env.AWS_ACCESS_KEY_ID ?? "",
      secretAccessKey: process.env.AWS_SECRET_ACCESS_KEY ?? "",
      sessionToken: process.env.AWS_SESSION_TOKEN,
      region: process.env.AWS_REGION ?? "us-east-1",
      service: "appsync",
    });
  }
  return signer;
}

/**
 * Publishes a twin-state update by calling a "local" AppSync mutation over its HTTP
 * endpoint, IAM (SigV4)-signed. The schema wires `Mutation.publishTwinUpdate` to a
 * local (no-op) resolver decorated `@aws_subscribe(["onTwinUpdate"])`, so this call
 * fans out to every connected `onTwinUpdate(turbineId)` subscriber without this
 * Lambda needing to know who's subscribed.
 *
 * DECISION (documented per task): chose the mutation-trigger pattern over writing an
 * AppSync JS resolver directly, because the state this service publishes originates
 * outside AppSync (an EventBridge-triggered Lambda reading DynamoDB) — a JS resolver
 * only runs in response to an incoming AppSync request, so it has no way to
 * originate a push on its own. The mutation-trigger pattern is the standard way to
 * drive an AppSync subscription from an external event source.
 */
export async function publishTwinUpdate(twinState: TwinState): Promise<void> {
  const endpoint = process.env.APPSYNC_GRAPHQL_URL;
  if (!endpoint) {
    throw new Error("APPSYNC_GRAPHQL_URL is not configured.");
  }

  const response = await getSigner().fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query: MUTATION,
      variables: { input: twinState },
    }),
  });

  if (!response.ok) {
    throw new Error(`AppSync mutation returned HTTP ${response.status}`);
  }

  const body = (await response.json()) as { errors?: Array<{ message: string }> };
  if (body.errors?.length) {
    throw new Error(`AppSync mutation returned errors: ${body.errors.map((e) => e.message).join("; ")}`);
  }
}
