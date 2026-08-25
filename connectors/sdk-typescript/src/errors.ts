export class ConnectorSdkError extends Error {
  readonly code: string;
  readonly statusCode: number;

  constructor(code: string, message: string, statusCode = 400) {
    super(message);
    this.name = "ConnectorSdkError";
    this.code = code;
    this.statusCode = statusCode;
  }
}
