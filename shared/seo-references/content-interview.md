# Topic research and operator interview

Use this for new articles, substantial topic refreshes and substantive website copy. It applies
to both the host-written website path and the scripted publication path. Minor corrections
and diagnostic technical repairs do not need a fresh interview. Company knowledge stays in
the target workspace, not in reusable skill instructions or the human-writing corpus.
Read `.seo-engine/knowledge.md` when present for the audience, positioning and existing
constraints before research or interview questions. Update that brief with useful, agreed
context; it never supplies publication permission for a new topic.

## Research existing answers

Before asking questions, inspect search results and read relevant competing pages. Use the
existing research collector for Google SERPs, keyword/demand evidence and page retrieval;
Ahrefs/GSC and other configured providers can supplement it. Do not require every provider
or spend without existing authority. Save actual responses in the target's ignored state.
Missing volume is unknown, not zero. If Google results are unavailable, identify the fallback
and its limits explicitly. Never present a seed-only investigation as a Google SERP analysis.

Record reader intent, inspected URLs, what each page explains, omissions in those inspected
pages, demand evidence (or its diagnosed absence), and unresolved questions. A gap in inspected
pages is not proof that nobody has covered it. External evidence still needs contextual review.

## Interview for this topic

Follow the question-interface rule below. Begin with two or three questions informed by the
research gaps, then follow up on concrete answers:
what happened, what the operator did differently, why, what failed, and when the lesson would
not apply. Do not ask the operator to do keyword research or author a JSON brief.

Prior company context helps avoid repetition, but never supplies blanket permission. Each new
topic gets an interview. A resumed run with unchanged approved material does not repeat it.
For a substantive refresh, ask what has changed and recheck the intended use. If the operator
has no relevant contribution or declines to share, record that and propose an `external_only`
piece with a useful comparison, tested example or synthesis; never manufacture expertise.
If no useful contribution can be supported, choose another topic rather than pad a draft.

### Question interface

Use the host's native structured question tool for onboarding and topic interviews, including
follow-ups. Check the tools exposed in the current session and their usage restrictions before
asking. Examples include Codex `request_user_input_async` or `request_user_input`, and Claude
Code `AskUserQuestion`; names and availability depend on the host, not the model vendor.
If a synchronous tool is unavailable in the current mode, check for an available async
equivalent before falling back. Do not print a questionnaire in chat when a suitable question
tool is callable. Use free-text input for experience and nuance; use choices for actual choices.

After an async question, keep the answer pending and continue only independent work. Do not
draft the dependent contribution or infer an answer from silence. Fall back to chat only when
no suitable tool is available/permitted or a tool fails without a usable alternative. State
the specific limitation in one short sentence before asking in chat. For disclosure approval,
use the question tool only if its rules permit approval requests; otherwise ask explicitly in
chat. The approval requirement below applies regardless of interface.

## Confirm proposed use

Show a concise summary of the proposed insight/example, limits, attribution and omissions.
Ask whether that proposed use is accurate and approved for this specific article/page. An
answer is not automatically permission. Reuse explicit permission already given for the same
material and scope. Publication/deployment authority remains a separate question.

Keep raw private answers out of this record, public Markdown, git, remote research queries and
downstream model prompts. Store only proposed publishable text and safe omission instructions
such as "omit client identity", not the actual excluded name. Do not promise that a hosted
agent conversation is confidential from its service provider. A record's confirmation is an
audit of the operator decision, not cryptographic proof that the human was asked.

## Record and resume

The host writes a JSON proposal in ignored target state. Example shape (illustrative, not
permission or factual evidence):

```json
{
  "topic": "How to evaluate an agency",
  "reader_intent": "Decide what evidence demonstrates useful agency work.",
  "demand_evidence": "Reference inspected SERP/keyword receipts; explain unavailable metrics.",
  "competing_pages": [{"url": "https://example.org/guide", "coverage": "What was actually read", "gap": "What that page leaves unresolved"}],
  "unresolved": "Which reported signals the operator has found misleading, and why.",
  "interview_summary": "Publishable summary of the operator's topic-specific answer.",
  "contribution": "The concrete useful addition this piece will make.",
  "mode": "firsthand",
  "items": [{"id": "lesson", "text": "Exact proposed publishable account from the operator.", "kind": "experience", "attribution": "Our operations team", "limits": "Experience within our own work, not an industry-wide result."}],
  "constraints": ["Omit client identities and contract figures."],
  "research_digest": "Digest returned by publication research; empty for host-written pages."
}
```

Item kinds are `experience`, `opinion`, or `measurement`. `external_only` has an empty `items`
list and an interview summary explaining the operator's decision. All other fields still
apply. An interview measurement may support only the scope/period actually discussed; it
does not prove a general causal claim. No fake public URL is needed for interview evidence.

Use the installed `pub-research` skill's `scripts/content_brief.py` from the target root:

```bash
python3 "$PUB_RESEARCH_DIR/scripts/content_brief.py" --action prepare --content-id publication:newsletter:agency-guide --file .seo-engine/reports/proposed-use.json
python3 "$PUB_RESEARCH_DIR/scripts/content_brief.py" --action confirm --content-id publication:newsletter:agency-guide --confirm-digest EXACT_APPROVED_DIGEST --operator "Operator identity" --confirmation "Actual explicit approval for the proposed use"
python3 "$PUB_RESEARCH_DIR/scripts/content_brief.py" --action status --content-id publication:newsletter:agency-guide
```

Run `confirm` only after receiving the actual approval (including an earlier explicit approval
of this exact proposed use). The digest binds it to the presented proposal. Changing a proposal
clears permission; re-preparing identical input preserves it. Unattended work pauses at
`awaiting_interview` or `awaiting_confirmation` without marking a draft ready.

For publications, initial `research_outline.py` gathers sources, returns the research digest
and pauses. The host inspects those sources, completes the record above, then reruns research
to outline from the approved contribution. The writer checks that permission and source
evidence still match. Use `--refresh-research` for a fresh investigation. A renamed thesis or
new disclosure scope needs an updated proposal, not automatic reuse of old permission.

For website copy, use `content_id: page:/target-path`; put the returned `content_brief` reference
in the growth brief's `content_briefs[page_path]`. Read its approved material before editing.
After editing, write a JSON object mapping page paths to reviews with `disclosure_checked: true`
and a specific `value_added` explanation. Pass it using `run_growth.py --stage validate --id ID
--content-review-file FILE`; the command stores it in the job as `content_reviews`. Editing
the original brief JSON does not update an existing job. The scripts enforce recorded permission, not the timing of
arbitrary manual source edits, so the host must perform the interview before writing.

## Outline, write and review

Organize around the reader's task and approved contribution; combine external evidence with
attributed firsthand experience without turning either into unsupported generalizations.
Use the existing human corpus for technique, record selected examples, and preserve brand
voice. A fixed word count, opening statistic or section quota is not required. The explicit
long-read template remains available when it fits the task.

Review final body, visible title/summary, source list, metadata, diagrams and covers. Check
the promised contribution is present, attribution is accurate, limitations survive and
excluded information has not reappeared. In publication review JSON, use `interview:ITEM_ID`
as a claim's `source` and quote its approved text; public sources keep their URLs. Record
`disclosure_checked: true` along with the existing facts/claim assessments. A boolean records
accountable review, not automated semantic proof. Changed permission, evidence or content
invalidates the review; a publication/deployment approval cannot override that check.
