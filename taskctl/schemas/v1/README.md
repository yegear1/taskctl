# taskctl payload schemas v1

Version **1.0.0**. Documents are JSON Schema draft 2020-12.

| Contract | Path | Producer |
|---|---|---|
| Generic webhook event | `taskctl/schemas/v1/webhook-event.schema.json` | `WebhookDispatcher` for URLs that are not Discord or Slack |
| Vector telemetry event | `taskctl/schemas/v1/vector-event.schema.json` | `TelemetryEvent.to_dict()` / `VectorSink` |

Discord (`embeds`) and Slack (`blocks`) bodies are transport adapters. They are not valid instances of the generic webhook schema.

`taskctl.schemas.validate_instance` checks the keyword subset these files use: `type`, `properties`, `required`, `additionalProperties`, `enum`, `minLength`, `pattern`, `minimum`, and `maximum`. Annotation keywords (`title`, `description`, `$id`, `$schema`, `x-taskctl-schema-version`) are ignored.
