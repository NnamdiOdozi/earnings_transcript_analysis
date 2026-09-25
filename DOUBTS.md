# Doubts

Decisions taken during a session without asking first, written down so they get
reviewed rather than silently inherited. Each entry says what was decided, why, and
what could go wrong if the decision was the wrong one.

Written to be read by the project owner, not only by someone reading the code. If an
entry here needs a glossary to follow, it is written badly and should be rewritten.

Newest first.

---

## 1. [2026-09-25] The reviewer's checklist is just a list of claim numbers, with no note against each one

**What was decided.** When the reviewer finishes checking claims, it writes down four
lists of claim numbers: the ones it read and was happy with, the ones it raised a problem
about, the ones it could not judge, and (on a repeat review) the ones it is carrying over
unchanged from last time. It does not write a sentence about each claim.

**Why.** The reviewer can read files and write files, and that is all — it cannot run any
code. So every one of those claim numbers is typed out by hand. The biggest real run has
203 claims. Four plain lists it can copy off the claims file are manageable. Asking for a
short written note against all 203 would be a lot of writing on every review round, and
the reasons for any actual problem are already written out in the findings.

**What this does and doesn't buy us.** It means a review that quietly looked at 20 claims
out of 203 can no longer look identical to one that looked at all of them — the lists
have to add up to every claim, and the program refuses the review if they don't. It does
**not** prove the reviewer actually read anything: in principle it could copy the claim
numbers across without looking. We are catching "you skipped claims", not "you didn't
look properly".

**The risk if this was the wrong call.** If we ever suspect the reviewer is going through
the motions, this checklist won't tell us. The fix then would be to ask for a short note
per claim, which is a bigger change than adding a field — it changes the shape of what
the reviewer writes.

**Does anything have to happen?** No. Leave it unless there is a reason to doubt the
reviewer's diligence.

---

## 2. [2026-09-25] Runs that were already approved don't have to produce the new checklist

**What was decided.** The new checklist is required for every review from now on. The one
exception is re-running the final command on a run that was **already approved and whose
files have not changed since**. Those reviews are let through without a checklist.

**Why.** Every review written before today has no checklist, because the field didn't
exist. Without this exception, a run you already signed off could never be re-confirmed
again — the program would refuse it for breaking a rule that was invented after it was
approved. The project already made exactly this allowance once before, for the extraction
coverage receipt.

**The risk if this was the wrong call.** There is a small hole. Someone could re-run the
final command on an untouched, already-approved run and get "accepted" back without any
checklist. I judged that acceptable because nothing can actually change on that path: the
files are byte-for-byte the same ones that were approved, and the verdict it reports is
the same verdict already on record. It re-writes the summary file from unchanged inputs.
A genuinely new review — including a new review of an old run — still has to produce a
full checklist.

**Does anything have to happen?** No, but you should know the hole exists rather than
discover it later.

---

## 3. [2026-09-25] I moved some existing code in the same commit as a behaviour change

**What was decided.** A safety check built into this machine refused my edit. One function
in the review code was already flagged as too complicated, and my addition made it worse.
Rather than ask you to relax that limit, I moved a self-contained block of existing checks
out into a function of its own, which brought the score down comfortably.

**Why this is worth flagging.** This project's own convention is to keep "move code
around" and "change what the code does" in separate commits, so that anyone reviewing a
change can see the real difference without wading through a large block of text that just
got relocated. I broke that convention once here.

**The risk if this was the wrong call.** Low. The moved checks are identical, in the same
order, and the whole test suite passes. The complexity score actually improved from 46 to
37, so the code is in better shape than before, not worse. The only cost is that this
commit is slightly harder to read than two commits would have been.

**Does anything have to happen?** No. Nothing to undo.

---

## 4. [2026-09-25] This stricter review could stop runs from ever finishing, if we also make "medium" problems blocking

**This is the entry worth your attention.** The other three are housekeeping.

**The situation.** The reviewer used to check a sample of claims for whether the written
claim fairly represented the source. It now checks every single one. On a 200-claim run
that is roughly ten times as much checking, so it will find more things to complain about
— which is the point.

Separately, there is an item already on the deferred list, which you asked for, that would
make any "medium" severity problem block a run instead of merely warning about it. Today
only "high" and "critical" block.

Put those two together and there is a plausible failure: the reviewer finds a handful of
arguable medium problems on every run, each one blocks, a run gets three review rounds at
most, and runs start hitting that ceiling without ever being accepted.

**What I did about it.** The most likely source of a flood of arguable findings was a
suggestion to have the reviewer judge whether each quote is "representative" of its
source. Applied loosely across 200 claims, almost any short quote can be argued to be
unrepresentative. So the contract now says explicitly that a quote being short is not a
problem by itself, and sets a concrete test instead: does the text that was left out
change what a reader would conclude? That should keep the volume down.

**The risk if this was the wrong call.** If the wording isn't tight enough, we won't find
out until the medium-blocks-runs change goes in, and then runs will start failing for
reasons that look mysterious.

**What should happen.** Before implementing the medium-blocks-runs change, do one real
earnings run under the new contract and count how many medium findings come back. If it
is a handful, the two changes are compatible. If it is dozens, the finding thresholds need
tightening first, or the round limit needs raising.

**Not yet tested on a real run.** Everything above is reasoning, not evidence. The new
rules have been exercised with a stand-in reviewer that writes the right file shape and
makes no judgments, which proves the plumbing works and says nothing about how many
findings a real review produces.
