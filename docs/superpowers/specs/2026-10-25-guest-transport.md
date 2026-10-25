# Capri Guest transport spike: proposed scope

Source: the user's attached research, `Pasted text.txt`, supplied on 2026-10-25 after reverting the first Guest Mode implementation. This document distils that proposal; it does not treat its claims about external implementations as proof of Capri's behavior.

## Outcome and sequence

1. Telegram-only probe: an authenticated owner mention produces `Guest OK` through `answerGuestQuery`.
2. After live success of step 1, send `Думаю…`, wait 2 seconds, and edit the returned inline message to `Guest OK final`.
3. Isolated Luna integration and streaming require a separate plan after both live gates pass. No guest Engine/session work belongs to this spike.

## Constraints

- Windows x64; Python 3.14; aiogram==3.31.0; existing dependencies only.
- Owner-only access uses the already paired `owner.json` identity and the incoming real `from_user`; never authorize through usernames, text, or chat IDs. Reject missing/bot/chat senders. `guest_bot_caller_user` is not an incoming authorization fallback.
- Native `Router.guest_message`; polling uses `dp.resolve_used_update_types()` after router registration.
- Explicit `bot.answer_guest_query(guest_query_id=..., result=...)` uses `InlineQueryResultArticle` and `InputTextMessageContent`; edits use only its returned `inline_message_id`. No Message shortcut/context binding, ordinary sendMessage, drafts, DM fallback, or broad chat-history access.
- Missing, unreadable, malformed or invalid owner.json prints `guest_probe: owner pairing unavailable` and refuses before Bot construction/polling. Positive integer owner IDs only, excluding bool. A simple seen set reserves query IDs before awaiting; no capacity infrastructure.
- Probe must start no OMP child and must not read/write owner session.json or transcripts. Existing DM implementation is unchanged.
- Use a temporary, explicitly selected CLI probe mode. Stop the normal poller during live testing; private DM is temporarily unavailable in this mode. Restore the normal launcher afterward. Never run two pollers with the same token.
- Missing/expired queries, uncertain network outcomes and anonymous identities fail closed; log safe diagnostic categories without raw message bodies, query IDs, tokens or exceptions.
- No memory, stickers, reactions, timers, soul.md, media, npm bootstrap, generic agent harness or session abstractions. The 2-second delay is only a transport demonstration.
- No computer use. No commit/push without explicit authorization. Do not use GPT-6 Astra for subagents.

## Known evidence and unresolved condition

The previous debug run reported supports_guest_queries=True, but that is historical evidence and must be checked again. Two incoming guest updates had from_user.id=1087968824, is_bot=True and sender_chat present, with no guest_bot_caller_user. They were correctly rejected under owner-only policy. This disproves an explanation based solely on missing polling subscriptions. It does not establish why Telegram supplied that identity or whether every supported chat behaves the same way.

An authorized live update is required for success. If identity remains anonymous, record BLOCKED before answerGuestQuery; do not silently enable public access. A human DM/group where Capri is absent is the baseline. Saved Messages and another bot's DM are separate client/chat experiments, not assumed supported or unsupported.

## Source contract checked on 2026-10-25

- [Telegram Bot API](https://core.telegram.org/bots/api#answerguestquery): guest response and inline edit contract; incoming/outgoing field meanings.
- [aiogram 3.31 SentGuestMessage](https://docs.aiogram.dev/en/v3.31.0/api/types/sent_guest_message.html): typed response exposes inline_message_id.
- [telegram-ai-searcher guest.ts](https://github.com/backmeupplz/telegram-ai-searcher/blob/master/src/guest.ts): reference sender extraction uses message.from. Do not copy its media/rate-limit architecture.
- [Hermes PR #56476](https://github.com/NousResearch/hermes-agent/pull/56476): contains historical revisions and conflicting earlier comments; the September rewrite describes native guest updates and from_user. Its reported live success is not Capri acceptance evidence.

## Acceptance evidence

Record observed capability, resolved update types, authorization outcome, answer acknowledgment, inline edit acknowledgment and the owner's visual confirmation. Use PASS / FAIL / BLOCKED for each stage. A mocked success or HTTP acknowledgment alone is not proof that a reply appeared in the intended chat.
