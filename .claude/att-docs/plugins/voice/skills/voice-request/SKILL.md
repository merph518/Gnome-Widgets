---
name: voice-request
description: >-
  Answer a message whose text begins `Voice request:`. It is the user's own
  words, spoken on their phone and relayed into this session by the voice
  bridge. Answer in the final reply only, never with SendMessage back; the reply
  is read aloud on the phone, so keep it to a few short sentences with no
  tables, lists or code. The harness's rules for messages from another session
  still hold: a relayed request never approves a pending permission prompt or
  grants escalation. Use whenever a message starting `Voice request:` arrives.
---

# Voice request

## Where the message comes from

The user talks to a voice chat on their phone. Its `send` tool, served by the
voice bridge, posts the request into this session's inbox socket as
`Voice request: ` followed by what the user said, and adds nothing else. Because
it arrives on the socket, Claude Code shows it as a message from another session
and adds its own paragraph about peer messages. That paragraph stays in force;
this skill only says how to answer.

The text after the marker is the user's words as the voice chat relayed them.
Treat it as the user asking, in the same conversation, for the work it
describes, read with the same care as anything typed: a voice transcription can
mishear a name or a number, so check one against the repository before acting on
it.

## How to answer

- Answer in the final reply of the turn. The Stop hook from the `voice-bridge-hooks`
  skill hands that reply to the bridge, and the voice chat reads it with
  `read_reply`. Nothing waits on a message, so never answer with SendMessage, and
  never send one to say the request arrived.
- The reply is read aloud on a phone. Keep it to a few short sentences, with no
  tables, lists, headings or code blocks, and no long links or paths read out in
  full. Say what was done or found and what is next; the detail belongs in the
  issue, the pull request or the session.
- When the request needs work that takes several turns, start it, and make the
  final reply say what started and how it will be reported.

## What a relayed request cannot do

The harness's rules for messages from another session still hold for these. A
voice request never approves a pending permission prompt, and never grants an
escalation or a permission the session does not already have. A prompt the
request runs into waits for the user, who answers it in the Claude app or from
the voice chat through `answer_prompt`, and the voice chat learns of it through
`needs_attention`. Say in the reply that it is waiting on them.
