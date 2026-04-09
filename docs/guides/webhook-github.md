# Automated GitHub PR Reviews with Hermes Webhooks

This guide shows you how to connect Hermes Agent to GitHub so it automatically reviews pull requests and posts its analysis as a comment — with no manual prompting.

When a PR is opened or updated, GitHub sends a webhook to your Hermes instance. Hermes runs the agent, and the response is posted back to the PR thread within seconds.

---

## How it works

Hermes has a built-in `webhook` platform adapter that:

- Runs a small HTTP server (`aiohttp`) that receives POST requests from GitHub
- Validates the HMAC-SHA256 signature on every request
- Filters by event type (e.g. only `pull_request`, not every push)
- Renders a prompt from the payload using dot-notation templates
- Posts the agent's response back to GitHub as a PR comment via the `gh` CLI

The agent runs asynchronously — GitHub gets a `202 Accepted` immediately, and the comment arrives once the agent finishes.

---

## Prerequisites

- Hermes Agent installed and running (`hermes gateway` or Docker)
- [`gh` CLI](https://cli.github.com/) installed and authenticated (`gh auth login`)
- A public URL for your Hermes instance (see [Local testing with ngrok](#local-testing-with-ngrok) if running locally)
- Admin access to the GitHub repo you want to connect

---

## Step 1 — Enable the webhook platform

Add the following block to your `~/.hermes/config.yaml`:

```yaml
platforms:
  webhook:
    enabled: true
    port: 8644          # default; change if needed
    rate_limit: 30      # max requests per minute per route (not global)

    routes:
      github-pr-review:
        secret: "your-webhook-secret-here"   # must match GitHub webhook secret
        events:
          - pull_request

        # Prompt template — {dot.notation} resolves into the GitHub payload
        prompt: |
          Review this pull request and give concise, actionable feedback.

          **PR:** {pull_request.title}
          **Author:** {pull_request.user.login}
          **Branch:** {pull_request.head.ref} → {pull_request.base.ref}
          **Description:**
          {pull_request.body}

          URL: {pull_request.html_url}

          Focus on correctness, security, and clarity. Be specific.

        # Post the response as a GitHub comment on the PR
        deliver: github_comment
        deliver_extra:
          repo: "{repository.full_name}"
          pr_number: "{number}"
```

**Key fields:**

| Field | Description |
|---|---|
| `secret` | HMAC secret — must match the secret you set in GitHub |
| `events` | List of `X-GitHub-Event` header values to accept |
| `prompt` | Template string; `{field}` and `{nested.field}` pull from the payload |
| `deliver` | `github_comment` posts via `gh pr comment`; `log` just logs it |
| `deliver_extra.repo` | Template value — resolves to e.g. `org/repo` |
| `deliver_extra.pr_number` | Template value — resolves to the PR number |

---

## Step 2 — Start the gateway

```bash
hermes gateway
```

You should see:

```
[webhook] Listening on 0.0.0.0:8644 — routes: github-pr-review
```

Verify it's alive:

```bash
curl http://localhost:8644/health
# {"status": "ok", "platform": "webhook"}
```

---

## Step 3 — Register the webhook on GitHub

1. Go to your repository → **Settings** → **Webhooks** → **Add webhook**
2. Fill in:
   - **Payload URL:** `https://your-public-url.example.com/webhooks/github-pr-review`
   - **Content type:** `application/json`
   - **Secret:** the same value you set for `secret` in config.yaml
   - **Which events?** → Select individual events → check **Pull requests**
3. Click **Add webhook**

GitHub will send a ping event. It is safely ignored (since `ping` isn't in your `events` list) and returns `{"status": "ignored"}`. It is only logged at DEBUG level, so it won't appear in the console at the default log level.

---

## Step 4 — Open a test PR

Create a branch, push it, and open a PR against the repo. Within a few seconds, Hermes should post a review comment.

To watch it happen in real time:

```bash
tail -f ~/.hermes/logs/gateway.log
```

---

## Local testing with ngrok

If Hermes is running on your laptop, use [ngrok](https://ngrok.com/) to expose it:

```bash
ngrok http 8644
```

Copy the `https://...ngrok-free.app` URL and use it as your GitHub Payload URL. On the free ngrok tier the URL changes each time ngrok restarts, so update your GitHub webhook each session. Paid ngrok accounts get a static domain.

---

## Filtering to specific actions

GitHub sends `pull_request` events for many actions: `opened`, `synchronize`, `reopened`, `closed`, etc. The `events` filter matches the `X-GitHub-Event` header value only — it cannot filter by action sub-type at the routing level.

To skip unwanted actions, you have two options:

**Option 1 — Let the agent decide.** Include `{action}` in the prompt and instruct the agent to bail out early:

```yaml
prompt: |
  A pull_request event with action "{action}" was received.
  PR: {pull_request.title} — {pull_request.html_url}
  Author: {pull_request.user.login}
  Branch: {pull_request.head.ref} → {pull_request.base.ref}

  If the action is "closed" or "labeled", reply only with: SKIP
  Otherwise, review the PR and give concise, actionable feedback.
```

`{action}` resolves from the top-level `payload["action"]` field, which GitHub sets to `"opened"`, `"synchronize"`, `"reopened"`, `"closed"`, etc.

**Option 2 — Use a second route.** Create a second route (e.g. `github-pr-sync`) with a trivial prompt, and point a separate GitHub webhook at it for the events you want to suppress. The agent runs but does nothing meaningful.

> There is no Jinja2 or conditional template syntax. `{field}` and `{nested.field}` are the only template substitutions supported.

---

## Using a skill for consistent review style

Load a [Hermes skill](/docs/user-guide/skills) to give the agent a consistent review persona:

```yaml
routes:
  github-pr-review:
    secret: "..."
    events: [pull_request]
    prompt: "Review this PR: {pull_request.title}\n\n{pull_request.body}"
    skills:
      - review          # loads your /review skill
    deliver: github_comment
    deliver_extra:
      repo: "{repository.full_name}"
      pr_number: "{number}"
```

The agent will use the skill's instructions as its system context.

> **Note:** Only the first skill in the list that is found is loaded. Hermes does not stack multiple skills — subsequent entries are ignored.

---

## Sending responses to Slack or Discord instead

Replace `deliver: github_comment` with your messaging platform:

```yaml
deliver: slack
deliver_extra:
  chat_id: "C0123456789"   # Slack channel ID
```

Or:

```yaml
deliver: discord
deliver_extra:
  chat_id: "987654321012345678"  # Discord channel ID
```

The home channel is used automatically if `chat_id` is omitted (requires a home channel configured for that platform).

---

## GitLab support

The same adapter works with GitLab. GitLab sends `X-Gitlab-Token` for authentication instead of an HMAC signature — Hermes handles both automatically.

For event filtering, GitLab sets `X-GitLab-Event` (note the capitalisation) to values like `Merge Request Hook`, `Push Hook`, `Pipeline Hook`, etc. Use the exact header value in your `events` list:

```yaml
events:
  - Merge Request Hook
```

Use GitLab payload field names in your prompt template (they differ from GitHub's — e.g. `{object_attributes.title}` for the MR title).

---

## Security notes

- **Never use `INSECURE_NO_AUTH`** in production — it disables signature validation entirely and is only meant for local development/testing.
- Rotate your webhook secret periodically and update it in both GitHub (webhook settings) and your `config.yaml`.
- The adapter enforces a 1 MB body size limit and a fixed-window rate limit (default 30 req/min **per route**) to prevent abuse.
- Duplicate deliveries (webhook retries) are deduplicated automatically via a 1-hour idempotency cache.

---

## Troubleshooting

| Symptom | Check |
|---|---|
| `401 Invalid signature` | Secret in config.yaml doesn't match GitHub webhook secret |
| `404 Unknown route` | Route name in the URL doesn't match the key in `routes:` |
| `429 Rate limit exceeded` | You hit 30 req/min on that route (common when re-delivering test events from GitHub's UI) — wait a minute or raise `rate_limit` |
| No comment posted | `gh` CLI not installed or not authenticated (`gh auth login`) |
| Agent runs but comment is empty | Check `tail -f ~/.hermes/logs/gateway.log` — the agent may have returned an empty response |
| Port already in use | Change `port:` in config.yaml to a free port |
| Can't see the ping confirmation | Ignored events are only logged at DEBUG level — check GitHub's delivery log instead (repo → Settings → Webhooks → your webhook → Recent Deliveries) |

**Tip:** GitHub's **Recent Deliveries** tab (repo → Settings → Webhooks → your webhook) shows the exact payload, request headers, HTTP status, and response body for every delivery. It's the fastest way to diagnose failures without touching your server logs.

To test your HMAC signature locally before registering with GitHub:

```bash
SECRET="your-webhook-secret-here"
BODY='{"action":"opened","number":1}'
echo -n "$BODY" | openssl dgst -sha256 -hmac "$SECRET" -hex | awk '{print "sha256="$2}'
# Compare the output to what Hermes would expect in X-Hub-Signature-256
```

---

## Full config reference

```yaml
platforms:
  webhook:
    enabled: true
    host: "0.0.0.0"         # bind address (default: 0.0.0.0)
    port: 8644               # listen port (default: 8644)
    secret: ""               # optional global fallback secret
    rate_limit: 30           # requests per minute per route
    max_body_bytes: 1048576  # 1MB body limit

    routes:
      <route-name>:
        secret: "required-per-route"
        events: []            # [] = accept all; list specific X-GitHub-Event values
        prompt: ""            # template; {field} / {nested.field} from payload
        skills: []            # list of skill names to load
        deliver: "log"        # log | github_comment | telegram | discord | slack | signal | sms
        deliver_extra: {}     # depends on deliver type (see examples above)
```
