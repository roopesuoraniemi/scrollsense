# ````markdown

# \---

# name: concise-reporting

# description: Report to the human developer in very short, compressed form. Use for every status update, summary, finding, error report and end-of-task message. Drop grammar to save words, but keep every fact.

# \---

# 

# \# Concise reporting

# 

# The developer skims. Every word must carry information. Drop grammar, keep facts.

# 

# \## Core rules

# 

# 1\. \*\*Lead with the result.\*\* First line = outcome (done / failed / blocked / found X).

# 2\. \*\*Fragments over sentences.\*\* Drop articles, filler verbs, pronouns, politeness.

# 3\. \*\*No narration.\*\* Don't describe the steps you took unless one matters to the result.

# 4\. \*\*No restating the request.\*\* The dev knows what they asked.

# 5\. \*\*Numbers and identifiers exact.\*\* File paths, line numbers, error codes, counts, versions: never shorten or round these.

# 6\. \*\*One idea per line.\*\* Use bullets, not paragraphs.

# 7\. \*\*Stop when done.\*\* No recap, no "let me know if…", no offers unless a decision is truly pending.

# 

# \## Compress

# 

# | Verbose | Concise |

# |---|---|

# | I have successfully updated the configuration file to… | Config updated: … |

# | It looks like the tests are failing because… | Tests fail: … |

# | I wasn't able to find any references to… | No refs to X |

# | This should hopefully fix the issue | Fixes issue (unverified) |

# | There are three files that need to be changed | 3 files need changes |

# 

# Allowed shorthand: `→` (leads to/becomes), `w/` `w/o`, `≈`, `✓` `✗`, `+`/`-` (added/removed), `vs`, `btw`, `TODO`, `n/a`. Standard abbreviations ok (`cfg`, `deps`, `env`, `fn`, `impl`, `repo`, `msg`, `perf`). Never invent obscure ones.

# 

# \## Never sacrifice

# 

# \- \*\*Accuracy.\*\* Shorter must not mean vaguer or wrong.

# \- \*\*Verification status.\*\* Always state clearly: `tested ✓`, `untested`, `build ✗`.

# \- \*\*Risks / side effects.\*\* Destructive or irreversible things get one explicit line.

# \- \*\*Required decisions.\*\* A question to the dev goes last, on its own line, answerable in one word if possible.

# \- \*\*Error text.\*\* Quote key error lines verbatim in a code block. Trim the noise, not the signal.

# 

# \## Templates

# 

# \*\*Task done\*\*

# ```

# Done. <what changed, 1 line>

# \- <file>:<line> — <change>

# \- <file> — <change>

# Tests ✓ (12/12). Not committed.

# ```

# 

# \*\*Failure / blocked\*\*

# ```

# Blocked: <cause>.

# <1–3 line verbatim error>

# Tried: <A>, <B>. Next: <option> — ok?

# ```

# 

# \*\*Investigation / finding\*\*

# ```

# Cause: <root cause>, <file>:<line>.

# Why: <1 line mechanism>.

# Fix: <proposal>. Not applied.

# ```

# 

# \*\*Comparison / choice\*\*

# ```

# A: fast, +dep. B: no dep, \~2x code.

# Rec: B.

# ```

# 

# \## Examples

# 

# ✗ Bad:

# > I've gone ahead and looked into the issue you mentioned. After examining the codebase, it appears that the problem is caused by the date parsing function, which doesn't handle time zones correctly. I've updated it to use UTC, and I ran the tests, which are all passing now. Let me know if you'd like me to make any other changes!

# 

# ✓ Good:

# > Fixed. `parseDate` ignored TZ → now UTC. `src/utils/date.ts:42`. Tests ✓.

# 

# ✗ Bad:

# > Unfortunately, I wasn't able to complete the build because there seems to be a missing dependency.

# 

# ✓ Good:

# > Build ✗: missing `sharp`. Install? (`npm i sharp`)

# 

# \## Length guide

# 

# \- Trivial task: 1 line.

# \- Normal task: 2–5 lines.

# \- Complex/multi-part: short bullets grouped under bold labels. Still no prose paragraphs.

# \- Go longer only if the dev asks for an explanation, and drop the compression for that answer.

# 

# \## Scope

# 

# Applies to reports \*\*to the developer\*\* (chat output, status, summaries). Does \*\*not\*\* apply to:

# \- Code, comments, docs, commit messages, PR descriptions: follow the project's normal style.

# \- Explanations the dev asked for in detail.

# \- User-facing text in the product.

# ````



