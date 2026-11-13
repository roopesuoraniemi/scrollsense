\---

name: grill
description: Interrogate the user about an epic, a design, a feature or an idea until nothing is left silently assumed, then write the result down in the form the project uses, an epic file, a design note, or an entry in the roadmap inbox. Use only when the user explicitly asks to be questioned - "grill me", "poke holes in this", "/grill". Do not use when the user asks to plan, scope, break down or discuss an issue, epic or roadmap item, even when it has open design decisions; plan with them directly, and if the open decisions are large, offer a grill in one line.
---

# Grill

Interview the user until the two of you share one picture of what is being built, then write that picture down where the project keeps such things. Do not plan, design, or write code until the picture is complete and the user has confirmed it.

The skill is project-agnostic. Where the roadmap is, where design notes live and how they are written, where epics go, where learnings for the next roadmap review wait, which language documents use: each is found in the environment or asked once in round one, then written to a conventions file that every later grill in the same workspace reads first (see the decision log section). Nothing is asked twice, and nothing has to be set up: the file is created the first time a convention is found or decided.

**Everything the grill writes is a local draft, except the design note.** Epic files are staging for the tracker; inbox entries are staging for the roadmap review. The user copies them out, shortened to what the destination needs, when they choose. Only the design note goes where others read it, in the repository on the ticket's branch, through the pull request.

## The subject and the mode

The argument is free text: `$ARGUMENTS`. Find the subject in it rather than treating the whole text as the subject; "grill me on epic PROJ-96" and "/grill epic from Jira ticket PROJ-96" both mean PROJ-96.

Two modes, chosen from what the subject is, never from a keyword. If the subject does not say which, round one opens with one extra question, mode, recommended like any other.

|Mode|Subject|Depth|Finishes as|
|-|-|-|-|
|**epic**|an epic, a roadmap item, a tracker issue of type Epic|the outcome, not the how|an epic file|
|**design**|a story, a task, a feature, a design question|the whole tree, above a floor|a design note, when one is due|

A third, shorter finish exists inside epic mode: when the routing question in round one shows the subject is not work yet but one of the roadmap's inputs, and the user wants only that recorded, the grill finishes as **an inbox entry** (see the inbox section) instead of an epic file. A subject the user wants to understand, a strategy idea or a candidate item, gets the full epic grill even when nobody will build it yet.

A bug is not a subject. Most fixes need only the fix and the gate; grill a bug only when fixing it changes a design decision, and say so instead of starting a round.

## Facts first

**Facts are your job. Decisions are the user's.** Before round one, gather what the environment can tell you, and never ask the user for any of it:

* **The tracker**, read-only, through whatever tools are connected: the issue's summary, description, type, parent, linked issues and children.
* **The project's conventions**: `CLAUDE.md`, `AGENTS.md`, `CONTRIBUTING.md` or a README. Follow them. Epics and design notes are written in English unless the conventions say otherwise, whatever language the conversation is in.
* **The roadmap**: a file or folder named like `roadmap\*`, `plans`, `docs/roadmap`, in the repository or in the documents folder the user has pointed to before. If none can be found, ask where it is, or whether there is none.
* **The roadmap inbox**: a file named like `inbox.md` or `for-next-review.md` beside the roadmap, where learnings wait for the next review. Found with the roadmap, or asked in the same question; "none" is an answer and is recorded so it is never asked again. A project with no roadmap has no inbox.
* **Design notes**: `design/`, `docs/design/`, `docs/adr/`, `\*/design/`. Read the ones covering the area and note their style; the finished note must match it and is edited, not duplicated.
* **The code**: what it already does. Proposing what already exists is the commonest failure. Read the module, check `git log` on the relevant paths, dispatch an Explore subagent for anything broader than a few files.

Do not block a round on a lookup: ask every frontier question that does not depend on it and bring the dependent ones next round. If a lookup changes a recommendation, say so.

**Facts found, shown before round one.** Open the first round with a block of at most five lines stating what the lookups established: what already exists in the code, which roadmap item the subject serves, which note covers the area, what the tracker issue says, which conventions apply. Every recommendation downstream rests on these, so the user must be able to correct a misreading here, before it propagates into the questions. A fact the user corrects is recorded in the log as corrected.

## The tree and the frontier

The work is a **design tree**. The root is the goal; every decision below it opens further decisions that only make sense once the parent is settled, and some answers close whole subtrees. The **frontier** is the set of decisions you can ask about right now without guessing at an answer you have not been given; a question that depends on a still-open question is not on the frontier yet. Each mode names its root, its first frontier and its stopping rule below.

## Rounds

In each round: recompute the frontier from everything settled; ask it through the **AskUserQuestion** tool in batches of at most four questions per call, most consequential first, so a frontier of twelve is three calls rather than a wall of text and the user can stop between calls; after the last batch rewrite the decision log; stop and wait. Never continue into the next round on your own.

**Every question carries a recommended answer** as its first option, labelled "(Recommended)". It shows your current understanding, so a wrong assumption is corrected early, and the user who agrees only clicks. **The confidence rule:** where you are genuinely unsure, the option loses the label and its description says in one clause that it is a guess and why, and the recap names the one decision in the batch you most want the user to look at. Convenience stays where it is deserved.

Shaping a question for the tool: the question is one complete sentence ending in a question mark; the header is a two-word label such as "Scope". Two to four options, each a distinct choice, the trade-off in the option's description rather than in the question; the tool adds a free-text "Other" by itself. Use multi-select when the choices are not exclusive, such as which of these are in scope. A question with no natural options, a name or a date, still goes through the tool with the recommendation and one plausible alternative; the real answer comes under "Other".

Between batches write at most one line in chat, what the previous batch settled, one clause per decision, so a misreading is caught before it propagates. Do not restate the questions; the tool showed them. If the tool is not available in the session, fall back to a plain numbered list, recommendation on the following line, no decoration.

**A question from the user between batches is input, not a detour.** Answer it in a few lines, say in one clause what the answer opened if anything, and put that on the frontier for the next batch rather than exploring it in chat. The log records it with "the user asked" as its reason. In design mode the floor still applies: an aside below it is answered and listed as the implementer's call, not turned into a question.

**Stopping early.** If the user says "stop" or "that's enough", stop: list the branches you would have asked about and mark them as assumptions in the log. In design mode the review-risk question is asked even then, since the pull-request gate depends on that one answer.

### Pace and flavour

The chat around the dropdowns may be a little playful, under one rule: nothing decorative ever enters a question, an option or a description, and each piece carries real information. Open each round with a one-line **doneness meter**, the grill's own gauge, no percentages: `Round 2 · medium rare · 6 settled, 5 on the frontier`, rare for the first round, medium once more is settled than open, well done when the frontier is empty. In the recap between batches **draw the tree** as it stands, at most a dozen lines and 64 characters wide, settled branches ticked, the frontier marked, and a subtree a "no" closed collapsed into one line with the number of questions it saved; a closed subtree is the most satisfying moment of a grill, show it every time:



When the frontier is empty, before asking for confirmation, print **the receipt**: monospace, a dozen lines, no emoji, the subject and the counts of decisions, assumptions, non-goals and subtrees closed, the rounds it took, what it finishes as, closed with "well done". That is the whole repertoire: no badges, no streaks, no jokes inside the questions. If the user asks for a plainer run, keep only the one-line recap.

## Judgment questions

Dropdowns with a recommendation first are convenient, and convenience is the risk: the better the recommendations, the more tempting it is to click through. So at a few fixed points, listed per mode below, a question is asked in plain chat with no options and no recommendation. They are the questions whose answer depends on what the user wants rather than on what the code allows, and each should produce a sentence the finished artifact needs.

**The order rule.** Ask in the user's own words, wait, and only then show what you would have said, as a comparison: where the two differ and whether it matters. Showing the recommendation first turns free text into an edit of your sentence, and the point is an unanchored picture.

**Orient before asking.** Each judgment question opens with one sentence saying what kind of answer is wanted and why it is asked now, and a question that uses a technique with a name explains the technique every time, in a clause, because not everyone has met it. The pre-mortem is the standing example: it is a thought experiment done now, not a question to answer later. Say so, and phrase it as an instruction to imagine: "Imagine it is May 2027 and this epic turned out to be a waste. Looking back from there, what went wrong? Answering now is the point: the most likely failure, named today, is the one the epic can still guard against."

No other free-text questions. Technical nuances stay in the dropdowns, where ten clicks is the right price for ten decisions.

## The decision log, written every round

After every round rewrite one small file, whole, so it is always current:

```
<workspace root>/.grill/<slug>.md
```

The workspace root is the directory the session was opened in, or the folder the user has connected to the session; `<slug>` is the subject, an issue key or a short name.

**Where the user can see it.** Before round one, check whether the user can open the folder you write to. In a desktop or web session with no folder connected, the session's own storage is invisible to them: write the log there for your own resumption, but say in round one that the conventions file will not outlive the session, hand the log over as a file when the frontier empties, and at confirmation hand over every file the grill wrote. Never refer the user to a path they cannot open.

When the root is itself a git repository, keep `.grill/` out of it: if `.gitignore` does not already cover it, add `.grill/` to `.git/info/exclude`, which ignores it without touching a tracked file, and say so once in chat the first time. A plain folder of repositories needs nothing.

The log holds, in order: a status line (`FRONTIER OPEN`, `FRONTIER EMPTY, awaiting confirmation`, `CONFIRMED <date>`); the facts found, with any the user corrected; the goal; each settled decision with its answer **and its reason**; the open frontier; assumptions on record; non-goals; in design mode, the implementer's calls; and **learnings above this subject**, in two lists, for the epic and for the roadmap review, each omitted when empty (see the inbox section). A log whose frontier is not empty says so on its first line, so a stopped grill is never mistaken for a finished design.

**The conventions file**, `<workspace root>/.grill/conventions.md`, is shared by every grill in the workspace. It holds one short entry per project found in the workspace, keyed by repository or project name: where the roadmap is, where its inbox is or that there is none, where design notes live and in what style, where epics are posted, the document language, the tracker's project key. Read it before the lookups, so a known convention is not searched for again; write it the first time a convention is found or decided, and amend it when the user corrects one. It is created automatically, never by the user, and because it lives in the workspace it is consistent for one developer without being imposed on another.

A grill can outlive a context window or a session; the log is where the picture lives if the chat is compacted, and the user may correct it between rounds instead of answering in chat. Before round one, resume from an existing log for the same project and subject.

## Finishing

When the frontier is empty: the pre-mortem, the receipt, then show the log and ask the user to confirm it. Only after that confirmation write the durable artifact the mode names below, apply the learnings to the epic file and the inbox as the inbox section says, and name in one line each what moved where. When the user cannot browse the workspace, attach every file written, the log included; a file the user has not received is not finished. The log stays as the history and the "why".

## Learnings and the roadmap inbox

A grill learns things above its subject: a fact that would have changed the roadmap had it been known, a dependency the epic did not list, a done-sentence that cannot be verified as written. These are kept in the log under **learnings above this subject** and, at confirmation, moved one rung up the ladder, never two when one will do:

* **For the epic**, from a design grill: the local epic file is edited in its out-of-scope, dependencies or pointers sections, the way a design note is edited in place. It reaches the tracker when the user next syncs it. A ticket that belongs to no epic has no middle rung; its learnings either qualify for the inbox or stay in the log, and the recap says so. The grill never creates an epic to have somewhere to put them.
* **For the roadmap review**, from either mode: an entry is appended to the inbox when the conventions name one. If the project has none, the list stays in the log and the final recap says in one line that it has no home.

**An entry is a learning, not a request.** "Clients will want X" is a request. "X cannot reach an installation on the client's network, and we do not know its path" is a learning. Each entry carries a date and a title, its source (a presales ask, a client project, the technical team's view of competitiveness, strategy or partners, or an epic by name), what was learned as a fact, one proposed disposition the review can accept or overrule, and an empty ruling slot. Most design grills produce none for the inbox and one or two for the epic; an empty list is omitted, never padded.

**When the subject itself is an input.** If the routing question in round one shows the subject is not work yet but something the review should hear, and the user does not want it shaped further, the grill shortens: settle only what an entry needs, the fact, the source and the proposed disposition, in one or two rounds, write the entry after confirmation, and stop. The receipt says "finishes as: inbox entry". An idea the user wants shaped, or built now, stays on the epic path.

**Where the inbox is not.** Never in `.grill/`, which holds working logs, and never created by the grill for a project that has none. Like the epics folder it is local staging: the user shortens its entries into whatever the review reads, and the review's ruling lands in the roadmap, not back in the inbox.

## Epic mode

**Root and first frontier.** The root is the roadmap item's impact clause, its "so that" or equivalent. The first frontier is the split: how many outcomes the item needs, which comes first, which have no dependencies.

**The roadmap is the driver.** An epic exists to move a roadmap item, so an epic that maps to no item is a routing decision before it is anything else: ask in round one which item it serves, or whether it is really one of the roadmap's inputs, what prospects ask for, what would make the product competitive, what a delivery taught, which belongs at the next roadmap review rather than in a developer's hands now. The routing question offers three answers: it serves an item; it is an input the review should hear, and the grill finishes as an inbox entry (see the inbox section); or it is not work yet but the user wants it shaped anyway, so the review decides on a full picture rather than a line. The third keeps the whole epic grill, and it is the recommended answer when the user came to find out what the subject is, as a strategy idea or a candidate item usually does. In the second and third cases the epic file's roadmap line reads "none, candidate roadmap input: <which>", and an inbox entry says so, so the review hears it.

**The impact clause must be checkable.** The roadmap verifies impact by asking at its review whether the so-that came true, so the epic names the signal the review will look for: a sales promise made on it, a prospect shown it, hours of hand work that fell, a client step taken. The question stays on the frontier until there is one.

**The outcome must be shown.** An epic closes when its outcome is demonstrated or accepted, so the done-sentence travels with a "shown by": the demo, or who accepts.

**Judgment questions**, in the user's own words, order rule applied:

1. At the start, before any dropdown: what does the world look like when this is done, and why does the company care. The outcome and the so-that, the two levels of the ladder that measure the epic.
2. At the so-that signal: what would we point at in the roadmap review. A chosen signal is one nobody checks; a written one is one the user will.
3. Before the receipt, the pre-mortem, introduced as a thought experiment done now: imagine the target month has come and this epic turned out to be a waste; looking back, what went wrong. It surfaces the non-goal or the dependency the dropdowns let through, and the answer feeds the out-of-scope list or the dependencies.

**Stop** when the done-sentence is unambiguous, verifiable by someone who did not write it and has its shown-by; the so-that has its signal; the non-goals are listed; what exists is separated from what the epic adds; the dependencies are known. Do not descend into how: that is the owner's design note later, through this skill in design mode.

**The artifact: the epic file**, where the project keeps epics, as found or decided in round one, commonly an `epics/` folder beside the roadmap, for the user to post in the tracker. Use this template unless the project has its own. It follows the measurement ladder: tickets are output, the outcome is the result verified by demo or acceptance, the so-that is the impact verified at the roadmap review. Effort is not in the file: sizing stays with the owner and lives in the tracker's estimate field on the epic.

```
# Epic: <title, an outcome>

\*\*Roadmap item:\*\* <name or key, or "none, candidate roadmap input: <which>">. \*\*Owner:\*\* \*(one person)\*. \*\*Depends on:\*\* <epics or nothing>.

## Outcome
<one paragraph: the state of the world when this is done>

## Done when
> <one sentence a stranger can verify>

\*\*Shown by:\*\* <the demo, or who accepts>

## So that
<the roadmap item's impact clause, applied to this epic>

\*\*Checked at the roadmap review by:\*\* <the signal: a promise made, a prospect shown, hours that fell, a client step taken>

## What exists already, and is not this epic's work
<facts, with file or doc pointers>

## What this epic adds
<numbered; what, not how>

## Out of scope
<bullets>

## Pointers for whoever picks it up, human or agent
<design notes, code paths, issue keys, data>

## Suggested first tickets
<three to five, a starting shape, not a list to follow>

## Back to the roadmap
<optional: what this grill learned that the next roadmap review should hear; omit when there is nothing. The same items go to the inbox as entries at confirmation>
```

## Design mode

**Root.** The outcome the epic or ticket states.

**The floor.** A decision is a grill question only if it is expensive to reverse once code exists, or if a reader of the design note would need it. Names, module layout, which helper goes where, and anything a pull-request reviewer can see and change in the diff are the implementer's call: do not ask, list them in the log so they are on record as deliberately open. The developer owns the implementation; the grill owns what would be costly to get wrong. A small ticket gets a short grill by construction.

**Subtrees that get skipped and should not:** scope, what is explicitly out; error and edge cases, bad input, partial failure, empty state; compatibility, existing callers, data migrations, API consumers, wire contracts; testing, what kind, how much, what counts as done; non-goals disguised as goals, performance, config knobs, extensibility nobody asked for; **review risk**, whether the change touches a database migration, authentication or authorisation, deployment configuration, or has an author new to the codebase, each of which calls for a second human reviewer at the pull request.

**Judgment questions**, in the user's own words, order rule applied:

1. At the start, intent and invariant: what is this change for, and what must still be true after it. The invariant lives in people's heads more often than in files and constrains every decision below; it becomes the note's opening and its rule sentence.
2. In the round that contains the first approach-level question, before that round's dropdowns, the road not taken: which approach the user already rejected, and why. The skill cannot know what was discarded, and the discard is the failure-the-alternative-would-have sentence the note needs.
3. Before the receipt, the pre-mortem, introduced as a thought experiment done now: imagine the change is merged and a month later it caused trouble; looking back, what was it. It surfaces the compatibility or edge case a dropdown lets pass, and the answer feeds the note's edge cases or its "what this is not".
4. Only when the frontier holds an extensibility or indirection decision, a new interface, a plugin point, a config knob: what is the next change the user actually expects in this area. A seam is added when a real one appears, not in anticipation; this tells the two apart, and a forecast is free text because only the user can make it.

**Stop** when the frontier above the floor is empty.

**The artifact: the design note, when one is due.** Notes are per area, not per change. Edit the area's existing note when the settled decisions change what it says; write a new note only when the grill opened an area no note covers; otherwise end with the log and nothing in the design folder, and say so in one line. Write in the project's style as read before round one, typically present tense, what is and the reason for it, the failure the alternative would have, a section on what this is not; no question-and-answer form, no decision history, no dates of rulings. Edit in place so the review shows a diff. At confirmation nothing is built yet, so mark what is not yet built the way the project marks it, a status line or a "Not built:" sentence, and leave the note on the ticket's branch beside the code that makes it true; the skill writes the file and leaves the branch to the user. When the repository cannot be reached from the session, the note is handed over as a file with one line saying which path it belongs at. When review risk was found, the note states in one line that the pull request needs a second human reviewer, and why.

The note carries no learnings: it describes what is. What the grill learned about the epic or the roadmap goes up the ladder as the inbox section says, and the implementer's calls stay in the log and never travel upward.

## Guards

Nothing is committed or pushed. Nothing is written to the tracker: no comments, no edits, no transitions. Nothing in the project's design folder, the epics folder or the inbox is written before the user's confirmation. Documents name roles, not people. The user is never pointed to a path they cannot open. The branch and the review are the user's.

