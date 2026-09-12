# Contributing to Attention!

## Commit messages and PR titles

Use semantic commits (Conventional Commits):

```text
type(scope): short description
```

The scope is optional. Use a lowercase type, a short lowercase scope such as
`queue`, `audio`, `codex`, or `claude`, and start the English description in
lowercase. Keep it concrete: describe the change rather than saying “update” or
“improvements”.

Supported types: `feat`, `fix`, `docs`, `refactor`, `perf`, `test`, `build`, `ci`,
`chore`, `style`, and `revert`. Use `!` before the colon for a breaking change and
explain its impact and migration in the body.

Examples:

```text
fix(queue): prevent muted turns from replaying
feat(audio): support custom starter files
docs: explain installation and removal
ci: validate pull request descriptions
feat(controls)!: rename the starter options tool
```

Apply this format to new commits, PR titles, and squash-merge titles. Keep each
commit focused on one logical change. Do not rewrite published history solely to
change its formatting.

## Commit bodies and pull requests

Use the same two sections for the commit body and PR description:

```markdown
**Because**

- Explain the user-visible problem, requirement, or reason for the change.

**This commit**

- Describe the resulting behavior and the relevant changes.
- State what you verified, including results and any remaining limitations.
```

Start directly with `**Because**`. GitHub already displays the title and branch.
Both headings are bold text, and each section needs at least one concrete bullet.
Replace the template comments with your own content. Keep small changes brief;
include a before/after example when it helps explain a larger change.

The **Validate PR title and body** GitHub Actions check validates the PR format
on creation and edits. Commit-message formatting is a contributor convention;
that check does not inspect every individual Git commit. Configuring this check
as a required merge check is a separate repository setting.

## Verification

The **macOS tests** workflow runs on every pull request and push to `main`, and
can also be started manually. It tests macOS 15 on Apple Silicon and Intel with
Python 3.12, builds both client packages, verifies their payload integrity, and
runs the suite including checked-in package consistency checks. Dependencies are
installed from `uv.lock`; the workflow fails if the lockfile needs updating.

The two real Codex sandbox probes remain opt-in. CI does not test audible
playback or system-audio permission prompts. Required merge checks are configured
separately in repository settings; this workflow does not publish releases.

Use the [development instructions](README.md#build-from-source) for runtime
tests and rebuilding the published packages. Report the checks you actually ran.
For documentation-only changes, verify formatting and links. For changes to a
workflow, verify both accepted and rejected inputs. Do not present local tests as
proof of playback on other hardware or a clean-machine installation.
