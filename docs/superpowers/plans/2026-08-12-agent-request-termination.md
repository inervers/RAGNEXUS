# Agent Request Termination Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bound stalled Agent provider calls and suppress disabled-button animation.

**Architecture:** Configure the real OpenAI client with a finite timeout and no retries. Hide the reusable WebGL effect at the native disabled-state boundary.

**Tech Stack:** OpenAI Python SDK 2.48.0, React 19, CSS, OGL, Docker.

## Global Constraints

- Per-call timeout: `60.0` seconds.
- SDK automatic retries: `0`.
- Error events remain sanitized.
- Disabled buttons remain legible and non-interactive.

---

### Task 1: Bound Agent provider calls

- [x] Add a failing real-client configuration test.
- [x] Confirm the SDK defaults were 600 seconds and two retries.
- [x] Set `timeout=60.0` and `max_retries=0`.
- [x] Run Agent monitoring, SSE, and full offline backend tests.

### Task 2: Stop disabled button effects

- [x] Record the failing computed style as `visibility: visible`.
- [x] Hide only the effect span for disabled buttons.
- [x] Run frontend tests, `build:check`, and production build.
- [x] Verify production-container computed style as `visibility: hidden`.
