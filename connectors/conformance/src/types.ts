export interface ConformanceFixture {
  schema_version: 1;
  tools: Record<string, { arguments: Record<string, unknown> }>;
}

export interface ConformanceCheck {
  name: string;
  ok: boolean;
  error?: string;
}

export interface ConformanceReport {
  ok: boolean;
  connector_id: string;
  connector_version: string;
  endpoint: string;
  checks: ConformanceCheck[];
}

export interface ConformanceOptions {
  manifest: Record<string, unknown>;
  fixture: ConformanceFixture;
  endpoint?: string;
  timeoutMs?: number;
  fetchImpl?: typeof fetch;
  manifestSchema?: Record<string, unknown>;
}
