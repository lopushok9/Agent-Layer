export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };
export type JsonObject = { [key: string]: JsonValue };
export type JsonSchema = Record<string, unknown>;

export type ConnectorTrust =
  | "community_read_only"
  | "verified_read_only"
  | "verified_write"
  | "local_development";

export interface ConnectorToolManifest {
  name: string;
  description: string;
  read_only: boolean;
  risk_level: "low" | "medium" | "high";
  input_schema: JsonSchema;
  output_schema: JsonSchema;
}

export interface ConnectorManifest {
  schema_version: 1;
  id: string;
  name: string;
  version: string;
  artifact_digest?: string;
  publisher: {
    id: string;
    name: string;
    url?: string;
  };
  agentlayer: {
    protocol_version: 1;
    runtime_range: string;
  };
  trust: ConnectorTrust;
  transport: {
    type: "https";
    url: string;
    timeout_ms?: number;
  };
  permissions: {
    wallet_address: boolean;
    transaction_intents: boolean;
    network_hosts: string[];
  };
  tools: ConnectorToolManifest[];
}

export interface ConnectorIdentity {
  id: string;
  version: string;
  artifact_digest?: string;
}

export interface ConnectorInvocationContext {
  chain?: string;
  network?: string;
  chain_id?: string | number;
  wallet_address?: string;
}

export interface ConnectorInvocationRequest {
  protocol_version: 1;
  request_id: string;
  connector: ConnectorIdentity;
  tool: string;
  arguments: JsonObject;
  context: ConnectorInvocationContext;
  issued_at?: string;
  expires_at?: string;
  nonce?: string;
}

export interface ConnectorReadResponse {
  protocol_version: 1;
  request_id: string;
  connector: ConnectorIdentity;
  tool: string;
  kind: "read_result";
  result: JsonValue;
  expires_at: string;
}

export type ConnectorReadHandler = (
  arguments_: JsonObject,
  context: Readonly<ConnectorInvocationContext>
) => JsonValue | Promise<JsonValue>;

export type ConnectorReadHandlers = Record<string, ConnectorReadHandler>;

export interface ReadOnlyConnectorDefinition {
  manifest: ConnectorManifest;
  handlers: ConnectorReadHandlers;
  responseTtlSeconds?: number;
}

export interface ReadOnlyConnector {
  readonly manifest: Readonly<ConnectorManifest>;
  invoke(request: ConnectorInvocationRequest): Promise<ConnectorReadResponse>;
}
