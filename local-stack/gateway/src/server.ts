/**
 * Local substitute for AWS AppSync (see BLUEPRINT.md §5, ADR-0004). Serves the
 * REAL schema.graphql unchanged - resolvers call the 5 Lambda handlers under
 * services/*\/src directly, in-process (verified: tsx resolves each service's own
 * relative imports and its own node_modules correctly across the package
 * boundary - see docs/LINUX_HOSTING_GUIDE.md for why this works without a real
 * Lambda runtime emulator).
 */
import { readFileSync } from "node:fs";
import { createServer } from "node:http";
import { fileURLToPath } from "node:url";
import path from "node:path";

import { ApolloServer } from "@apollo/server";
import { expressMiddleware } from "@apollo/server/express4";
import { makeExecutableSchema } from "@graphql-tools/schema";
import bodyParser from "body-parser";
import cors from "cors";
import express from "express";
import { GraphQLScalarType } from "graphql";
import { PubSub } from "graphql-subscriptions";
import { useServer } from "graphql-ws/lib/use/ws";
import { WebSocketServer } from "ws";

import { handler as telemetryHandler } from "../../../services/telemetry-api/src/handler.ts";
import { handler as predictionHandler } from "../../../services/prediction-api/src/handler.ts";
import { handler as alertingHandler } from "../../../services/alerting-service/src/handler.ts";
import { startScheduler } from "./scheduler.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCHEMA_PATH = path.resolve(
  __dirname, "..", "..", "..", "infra", "terraform", "modules", "appsync-api", "schema.graphql",
);
const PORT = Number(process.env.GATEWAY_PORT ?? 4000);
const TWIN_UPDATE_TOPIC = "TWIN_UPDATE";

const pubsub = new PubSub();

// AppSync implicitly declares @aws_subscribe and the AWSDateTime/AWSJSON scalars;
// plain graphql-js knows none of them, so they're declared here (the directive as
// a no-op - this gateway implements the actual subscription fan-out itself via
// PubSub below - and the scalars as pass-through) so the real, unmodified
// schema.graphql parses without editing it.
const typeDefs = `
  directive @aws_subscribe(mutations: [String!]) on FIELD_DEFINITION
  scalar AWSDateTime
  scalar AWSJSON
  ${readFileSync(SCHEMA_PATH, "utf-8")}
`;

const passthroughScalar = (name: string) =>
  new GraphQLScalarType({
    name,
    serialize: (value) => value,
    parseValue: (value) => value,
    parseLiteral: (ast) => ("value" in ast ? ast.value : null),
  });

const resolvers = {
  AWSDateTime: passthroughScalar("AWSDateTime"),
  AWSJSON: passthroughScalar("AWSJSON"),
  Query: {
    telemetry: async (_: unknown, args: Record<string, unknown>) => {
      return telemetryHandler({ arguments: args });
    },
    predictions: async (_: unknown, args: Record<string, unknown>) => {
      return predictionHandler({ arguments: args });
    },
    activeAlerts: async () => {
      return alertingHandler({ field: "activeAlerts", arguments: {} });
    },
  },
  Mutation: {
    // Mirrors the cloud's NONE-data-source resolver (see schema.graphql's comment
    // on publishTwinUpdate): echoes the input and fans it out to subscribers -
    // never invokes a Lambda itself.
    publishTwinUpdate: async (_: unknown, args: { input: Record<string, unknown> }) => {
      await pubsub.publish(TWIN_UPDATE_TOPIC, { onTwinUpdate: args.input });
      return args.input;
    },
  },
  Subscription: {
    onTwinUpdate: {
      subscribe: (_: unknown, args: { turbineId: string }) => {
        // graphql-subscriptions' PubSub has no server-side filtering, so
        // asyncIterator over the shared topic + a per-subscriber filter (a
        // client only receives updates for the turbineId it asked for).
        const iterator = pubsub.asyncIterator<{ onTwinUpdate: Record<string, unknown> }>([
          TWIN_UPDATE_TOPIC,
        ]);
        return {
          [Symbol.asyncIterator]() {
            return {
              async next() {
                for (;;) {
                  const result = await iterator.next();
                  if (result.done) return result;
                  const state = result.value.onTwinUpdate as { turbineId?: string };
                  if (state?.turbineId === args.turbineId) return result;
                }
              },
              return: iterator.return?.bind(iterator),
              throw: iterator.throw?.bind(iterator),
            };
          },
        };
      },
    },
  },
};

const schema = makeExecutableSchema({ typeDefs, resolvers });

const app = express();
const httpServer = createServer(app);

const wsServer = new WebSocketServer({ server: httpServer, path: "/graphql" });
const wsCleanup = useServer({ schema }, wsServer);

const apollo = new ApolloServer({
  schema,
  plugins: [
    {
      async serverWillStart() {
        return {
          async drainServer() {
            await wsCleanup.dispose();
          },
        };
      },
    },
  ],
});
await apollo.start();

app.use(
  "/graphql",
  cors(),
  bodyParser.json(),
  expressMiddleware(apollo),
);

app.get("/health", (_req, res) => {
  res.json({ status: "ok" });
});

httpServer.listen(PORT, () => {
  console.log(`Gateway listening on http://localhost:${PORT}/graphql (ws on the same path)`);
  startScheduler();
});
