# AI

**Tools.** Claude Code (Anthropic, Fable 5.1) in VS Code as the pair programmer for
the whole build: scaffolding the Django project, drafting the replay engine and its
tests from the brief's worked example, the API views, the Next.js console and these
documents. I reviewed every module as it landed and asked for changes where the
behaviour did not match the brief.

**What it got wrong that I caught.** The cycle endpoint re-derived the gateway's
coverage class *before* writing the cycle results (correct, so a stale gateway's first
good cycle counts as a check) and then called the shared "finish request" step, which
re-derived the class again, saw no change, and never recomputed the sensors'
coverage. Gateways turned `connected` while every sensor stayed `recoverable`; the
end-to-end worked-example test exposed it as `next_evaluation_at` coming back null at
day 15. The fix was to split the step into "refresh gateway" and "evaluate sensors"
so the cycle view could call them in the right order.

A second one: after making the stale rule strict (`now > due`), the job runner still
selected events with `due <= now` and handed the due time itself in as `now`, so the
transition was never applied and the drain loop spun forever. The suite hanging on a
run that had taken 17 seconds the previous time was the tell.

Also caught in tests I asked it to write: a replay test that fed a coverage change
dated after `now`, which the server can never produce, and acks and cycles timestamped
in the future that the 5-minute rule correctly rejected.
