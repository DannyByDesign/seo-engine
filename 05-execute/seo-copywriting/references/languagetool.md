# LanguageTool proofreading

The standard writing sequence is: read human examples → draft from research → run LanguageTool
→ resolve suggestions → recheck the final prose → editorial/factual review. The human corpus
supplies varied writing techniques; LanguageTool catches language problems. Neither substitutes
for the other or proves persuasive copy.

## Configure once

Use `.env` at the target repo. An owned server requires only its full check URL:

```dotenv
LANGUAGETOOL_URL=http://127.0.0.1:8081/v2/check
LANGUAGETOOL_LANGUAGE=en-US
LANGUAGETOOL_LEVEL=default
```

For the documented authenticated API, set:

```dotenv
LANGUAGETOOL_URL=https://api.languagetoolplus.com/v2/check
LANGUAGETOOL_USERNAME=account-email
LANGUAGETOOL_API_KEY=api-access-token
```

Use an account entitled to automated proofreading calls and its actual quota. API credentials
are sent as POST form fields only to that exact hosted endpoint. A custom owned server receives
no LanguageTool cloud credentials. Remote servers require HTTPS; loopback can use HTTP.
The public `api.languagetool.org` endpoint is rejected because its documentation forbids
automation. No automatic fallback sends drafts to a different service.

For self-hosting, follow the official server instructions: download and unpack LanguageTool,
create `server.properties`, then start the Java server from that directory:

```bash
java -cp languagetool-server.jar org.languagetool.server.HTTPServer --config server.properties --port 8081
```

No browser-origin or public-binding flag is needed for terminal checks on the same machine.
The self-hosted server has basic open-source checks; cloud-only AI rules are not included.
The repo does not silently install Java, download server binaries or buy a subscription.

## Run and interpret

Run `check_writing.py --file draft.md --language en-US` from the target repo. Use `--format text`
for extracted visible copy or `--format html` for static HTML. Use the actual language variant
such as `en-GB`, `de-DE` or `pt-BR`; generic `en`/`de` can omit spellchecking dictionaries.
With `--language auto`, set `LANGUAGETOOL_PREFERRED_VARIANTS`, for example `en-US,de-DE`.
Use `--level picky` for additional formal-style suggestions, not as a universal voice rule.

The checker submits at most 20 chunks per invocation, at most 10,000 characters each, without
blind retries. `LANGUAGETOOL_CHUNK_CHARS` may lower that bound (minimum 100). Requests are
spaced by at least three seconds within a process. This is not a shared account quota manager;
schedule one writing worker per endpoint or enforce quotas server-side for concurrent jobs.
Chunk boundaries can lose cross-boundary context; inspect surrounding prose for such cases.
Failures and incomplete responses retain partial coverage and never become a successful check.

Read the full local report using the returned path. It records exact checked text, source hash,
completed coverage, software/language metadata, rule IDs, context and suggested replacements.
Automatic article checks cover the body; frontmatter such as `title` and `dek` is excluded.
Before final review, also check those visible fields as a small text file with `--format text`.
The report states this coverage limit. Code, hidden HTML and HTML attributes are excluded too.
Offsets refer to normalized checked text, not Markdown/HTML source. Do not apply them directly
to a source file. The CLI itself prints only a compact result, not the entire draft.

Resolve clear errors; preserve correct names, quotations, figures and intended voice. Record
reasons for rejecting style suggestions in the copy review. `LANGUAGETOOL_DISABLED_RULES`
supports comma-separated rule IDs for established editorial exceptions; never disable all
warnings just to produce zero matches. Rerun after edits. No matches is a completed diagnostic,
not a quality score. A failure remains `not_checked`; preserve the draft and record the gap.

`pub-write` checks its generated draft automatically and rechecks after a successful Shredder
rewrite. `pub-enhance` includes `language` in its
default stages and checks after other edits, before editorial review. First-party copy uses
the same CLI. Use the smoke harness with `--only languagetool` to send one harmless known-error
sentence and verify configured access; a configured URL alone is not a successful live test.

## Official references

Checked against the official documentation on 2026-09-09:

- [HTTP API schema](https://languagetool.org/http-api/languagetool-swagger.json): authenticated host, POST form fields, languages, rules and matches.
- [Public API policy](https://dev.languagetool.org/public-http-api.html): automated use requires an owned instance or appropriate account.
- [Owned HTTP server](https://dev.languagetool.org/http-server): Java server setup and differences from cloud checks.
- [Proofreading API](https://languagetool.org/proofreading-api): account service and request limits.

These are setup references only; the writing corpus is fully local and depends on none of them.
