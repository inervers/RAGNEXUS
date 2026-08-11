# Agent Request Termination Design

## Goal

Prevent Agent writing from appearing to run forever when a provider stalls, and stop disabled action buttons from continuously displaying the specular sweep.

## Decision

Construct the Agent `OpenAI` client with a 60-second per-call timeout and SDK retries disabled. Existing workflow failure handling converts timeout exceptions into sanitized terminal events.

Hide the WebGL effect span whenever a `SpecularButton` is disabled. The label remains visible, but no sweep is rendered while a request runs or an API key is absent.

## Alternatives Rejected

- Frontend-only timeout leaves a backend worker running.
- A workflow watchdog cannot safely kill the blocking provider thread and leaves SDK retries uncontrolled.

## Verification

- Inspect the real OpenAI client timeout and retry configuration without a network request.
- Retain sanitized SSE failure-event tests.
- Verify disabled-effect computed style in a production container.
