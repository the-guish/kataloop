REPO: ${REPO}
PR NUMBER: ${PR_NUMBER}
HEAD COMMIT: ${HEAD_SHA}
REVIEW DEPTH: ${DEPTH}
MODEL: ${MODEL}
EFFORT: ${EFFORT}

Review this pull request for security vulnerabilities only.
Read the diff with `gh pr diff`, and read the surrounding code to judge each change in context.
Report only issues with a concrete way to exploit them, at high or medium confidence.
Skip style, performance, tests and denial of service.

## Inline comments

Post each finding as an inline comment on its line, in this form:

```
**Claude Code Security Review** · <High|Medium> severity

**Issue.** <What is wrong, in one or two sentences.>

**Exploit.** <How an attacker reaches it and what they gain.>

**Fix.** <The change that removes it.>
```

## Summary comment

Then post one summary comment with `gh pr comment ${PR_NUMBER}`, filled in from this template.
Use only the plain marks ✓ and ✗. Use no emoji.

```
## Claude Code Security Review

| | |
|---|---|
| **Result** | ✓ No security issues found |
| **Review depth** | ${DEPTH} |
| **Model** | `${MODEL}` |
| **Effort** | ${EFFORT} |
| **Commit** | `<first 7 characters of the head commit>` |
| **Scope** | <N> files changed, <short description of what the change does> |

### Findings

| Severity | Location | Issue |
|---|---|---|
| High | `path/to/file.py:42` | <one-line issue> |

### Areas checked

| Area | Result |
|---|---|
| <area> | ✓ <one line on what was checked and why it is safe> |

<sub>Automated review by Claude Code. It reports only issues with a concrete way to exploit them, at high or medium confidence. It does not replace a human review.</sub>
```

Fill it in like this:

- With findings, the result reads "✗ <N> security issues found (<n> high, <n> medium)".
- Without findings, replace the findings table with the line "None."
- List three to six areas that the change actually touches, such as untrusted input, secrets,
  file paths, network requests, dependencies or CI permissions. Mark an area that holds a finding
  with ✗ and point to the finding.
