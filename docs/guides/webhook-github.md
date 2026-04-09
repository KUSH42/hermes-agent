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
    rate_limit: 30      # max requests per minute across all routes

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

GitHub will send a ping event — you'll see it logged (and safely ignored, since `ping` isn't in your `events` list).

---

## Step 4 — Open a test PR

Create a branch, push it, and open a PR against the repo. Within a few seconds, Hermes should post a review comment.

To watch it happen in real time:

```bash
hermes logs --follow
```

---

## Local testing with ngrok

If Hermes is running on your laptop, use [ngrok](https://ngrok.com/) to expose it:

```bash
ngrok http 8644
```

Copy the `https://...ngrok-free.app` URL and use it as your GitHub Payload URL. The URL changes each time ngrok restarts, so this is best for development only.

---

## Filtering to specific actions

GitHub sends `pull_request` events for many actions: `opened`, `synchronize`, `reopened`, `closed`, etc. To only trigger on new PRs and updates (not closes), add an `actions` filter to your prompt template and rely on the payload:

```yaml
prompt: |
  {% if action == "closed" %}
  Skip this event.
  {% else %}
  Review this PR: {pull_request.title}
  ...
  {% endif %}
```

Or more simply, handle it in the prompt — the agent will naturally ignore irrelevant context.

To filter at the routing level (bypass the agent entirely for `closed`), you can use multiple routes with distinct names and set up separate GitHub webhooks pointing to each.

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

The same adapter works with GitLab. GitLab sends `X-Gitlab-Token` for authentication instead of an HMAC signature — Hermes handles both automatically. Change the event filter:

```yaml
events:
  - Merge Request Hook
```

And use the GitLab payload field names in your prompt template.

---

## Security notes

- **Never use `INSECURE_NO_AUTH`** in production — it disables signature validation entirely and is only meant for local development/testing.
- Rotate your webhook secret periodically and update it in both GitHub (webhook settings) and your `config.yaml`.
- The adapter enforces a 1 MB body size limit and a fixed-window rate limit (default 30 req/min) to prevent abuse.
- Duplicate deliveries (webhook retries) are deduplicated automatically via a 1-hour idempotency cache.

---

## Troubleshooting

| Symptom | Check |
|---|---|
| `401 Invalid signature` | Secret in config.yaml doesn't match GitHub webhook secret |
| `404 Unknown route` | Route name in the URL doesn't match the key in `routes:` |
| No comment posted | `gh` CLI not installed or not authenticated (`gh auth login`) |
| Agent runs but comment is empty | Check `hermes logs` — the agent may have returned an empty response |
| Port already in use | Change `port:` in config.yaml to a free port |

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
        deliver: "log"        # log | github_comment | telegram | discord | slack
        deliver_extra: {}     # depends on deliver type (see examples above)
```
