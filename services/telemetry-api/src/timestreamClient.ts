import {
  TimestreamQueryClient,
  QueryCommand,
  type Row,
  type ColumnInfo,
} from "@aws-sdk/client-timestream-query";

export interface TimestreamQueryResult {
  columnInfo: ColumnInfo[];
  rows: Row[];
}

let client: TimestreamQueryClient | undefined;

/** Lazily constructed singleton so unit tests never need a live AWS client. */
function getClient(): TimestreamQueryClient {
  if (!client) {
    client = new TimestreamQueryClient({ region: process.env.AWS_REGION });
  }
  return client;
}

/**
 * Runs a Timestream query and collects all pages into a single result.
 * Timestream's Query API has no server-side row cap comparable to a relational
 * `LIMIT`-free query being dangerous, but a pathological time range could still
 * paginate for a long time — this Lambda handler holds `pageLimit` pages max as a
 * safety valve rather than looping unbounded on `NextToken`.
 */
export async function runQuery(
  queryString: string,
  pageLimit = 20,
): Promise<TimestreamQueryResult> {
  const timestreamClient = getClient();
  let nextToken: string | undefined;
  let columnInfo: ColumnInfo[] = [];
  const rows: Row[] = [];
  let pages = 0;

  do {
    const command = new QueryCommand({
      QueryString: queryString,
      NextToken: nextToken,
    });
    const response = await timestreamClient.send(command);
    columnInfo = response.ColumnInfo ?? columnInfo;
    rows.push(...(response.Rows ?? []));
    nextToken = response.NextToken;
    pages += 1;
  } while (nextToken && pages < pageLimit);

  return { columnInfo, rows };
}
