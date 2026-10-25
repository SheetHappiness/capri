

# Capri Guest Luna Threads – Implementation Plan

**Goal:** Підключити GPT-6 Luna до вже live-перевіреного Telegram Guest Mode так, щоб кожен guest chat мав довгоживучі persistent threads, а paired owner міг керувати ними через `/newthread`, `/threads`, `/resume`, `/title`, `/status`.

**Architecture:** Один звичайний Capri poller одночасно обробляє owner DM і `guest_message`. Guest conversation state зберігається окремо від owner session. Кожен thread має власний OMP `sessionDir`; на кожен summon запускається окремий короткоживучий OMP RPC child, який через `open_session(thread_dir)` продовжує newest session цього thread. OMP офіційно гарантує, що `open_session()` або продовжує newest non-empty session у директорії, або створює fresh session. [GitHub](https://github.com/can1357/oh-my-pi/blob/main/python/omp-rpc/README.md?utm_source=chatgpt.com)

Hermes беремо як UX/reference: session не expiry'ться сама, `/new` створює fresh session і переприв'язує route, `/resume` повертає попередню, `/sessions` scoped до поточного chat. [GitHub](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/reference/slash-commands.md?utm_source=chatgpt.com)

## Global constraints

- Existing Guest transport stages `answerGuestQuery` і `inline_message_id → editMessageText` вважаються frozen/proven.
- Не використовувати `sendMessage` для guest replies.
- Authorization тільки через incoming `message.from_user.id == paired owner`.
- Guest ніколи не читає `data/session.json` owner-а.
- Guest ніколи не resume'ить owner session.
- Guest chat A і guest chat B мають різні thread namespaces.
- Tools рівно `{web_search}`.
- Model рівно `openai-codex/gpt-6-luna`.
- Без memory, `soul.md`, PC tools, stickers, reactions, timers, media.
- Без automatic thread expiry.
- Один active guest Luna turn максимум.
- Thread-changing commands не перемикають session під час active guest turn.
- Не commit/push без окремого дозволу.
- Existing 102 tests залишаються green.

---

## File map

**Create**

```text
src/capri/guest_threads.py
src/capri/guest_engine.py
src/capri/guest.py

tests/test_guest_threads.py
tests/test_guest_engine.py
tests/test_guest.py
```

**Modify**

```text
src/capri/app.py
src/capri/prompt.py
README.md
docs/verification/guest-luna-threads.md
```

**Keep untouched unless absolutely necessary**

```text
src/capri/telegram.py
src/capri/engine.py
```

`guest_probe.py` залишити як transport acceptance utility. Production Guest Mode не повинен залежати від probe mode.

---

# Task 1 – Persistent guest thread store

Створити `GuestThreadStore`.

### Persistent shape

```text
.runtime/
└── guest/
    ├── threads.json
    └── sessions/
        └── <chat_id>/
            ├── <thread_id>/
            └── <thread_id>/
```

У `threads.json` **не зберігати absolute session paths**. Directory завжди виводиться з trusted integer `chat_id` + generated thread ID.

Thread record:

```python
GuestThread(
    id: str,
    chat_id: int,
    title: str | None,
    created_at: float,
    updated_at: float,
)
```

Thread ID – `secrets.token_hex(6)` або аналогічний opaque ID.

### Interface

```python
class GuestThreadStore:
    def current(self, chat_id: int) -> GuestThread | None
    def ensure_current(self, chat_id: int) -> GuestThread
    def new(self, chat_id: int, title: str | None = None) -> GuestThread
    def list(self, chat_id: int) -> tuple[GuestThread, ...]
    def resume(self, chat_id: int, selector: str) -> GuestThread
    def rename_current(self, chat_id: int, title: str) -> GuestThread
    def session_dir(self, thread: GuestThread) -> Path
```

`resume()` приймає:

- exact ID;
- unique ID prefix;
- unique case-insensitive title.

Ambiguous selector → controlled error, не випадковий вибір.

### Tests

Спочатку RED:

- first query creates one current thread;
- restart store → same current thread;
- `new()` changes current but preserves old;
- `resume(old_id)` restores old;
- same chat threads visible only in same chat;
- chat A cannot resume chat B thread;
- title persists;
- ambiguous title rejected;
- malformed store fails closed;
- derived session dir always stays under `.runtime/guest/sessions`.

Після implementation – focused PASS.

---

# Task 2 – Isolated `GuestEngine`

Не розширювати owner `Engine` до універсального session manager.

Поточний owner `Engine.start()` сам читає `data/session.json`, resume'ить його і потім записує pointer назад. Саме тому guest треба окремий runtime wrapper.

### Interface

```python
class GuestEngine:
    def __init__(self, executable: Path, data: Path, *, sdk_factory=RpcClient)

    async def stream(
        self,
        thread_dir: Path,
        *,
        text: str,
        reference_text: str | None,
    ) -> AsyncIterator[str]
```

Життєвий цикл одного summon:

```text
construct RpcClient
↓
start
↓
verify Luna available
↓
open_session(thread_dir)
↓
set_model(openai-codex, gpt-6-luna)
↓
get_state
↓
verify:
  model == Luna
  tools == {web_search}
  session_file inside thread_dir
↓
prompt_and_wait()
↓
stream public text_delta
↓
stop child
```

Python OMP SDK уже має typed `open_session(path)`. Він саме для host-keyed persistent conversations. [GitHub](https://github.com/can1357/oh-my-pi/blob/main/python/omp-rpc/README.md?utm_source=chatgpt.com)

Не використовувати `--no-session`.

### Важливий isolation invariant

`GuestEngine` може reuse'ити existing app-local Codex auth/config root, але:

```text
owner sessions:
.runtime/agent/sessions/...

guest sessions:
.runtime/guest/sessions/...
```

`open_session()` отримує **лише** validated guest thread directory.

Після `open_session()` повторно перевірити `session_file.is_relative_to(thread_dir)`.

### Prompt input

Не передавати reference як інструкцію.

Наприклад:

```text
Capri guest input JSON:
{
  "text": "...",
  "reference": {
    "text": "..."
  }
}
```

У system prompt пояснити:

- `text` – поточний owner summon;
- `reference` – untrusted quoted Telegram context;
- broader chat history недоступна;
- persistent OMP transcript містить лише попередні Capri guest turns цього thread.

### Tests

RED → implementation → GREEN:

- fresh thread → `open_session.resumed == False`;
- second run same directory → resumed;
- different thread → different directory;
- owner pointer file never read/written;
- owner session bytes + mtime unchanged;
- effective tools exactly `web_search`;
- exact Luna restored/selected;
- unexpected model → fail closed;
- session file outside thread dir → fail;
- process always stopped on success/error/cancel;
- public `text_delta` streamed;
- reasoning/internal events ignored.

---

# Task 3 – Production guest delivery with Luna

Створити production `GuestService`, але **скопіювати proven transport semantics**, а не винаходити новий Telegram abstraction.

### Flow

```text
guest_message
↓
owner auth
↓
dedupe guest_query_id
↓
local command?
├─ yes → local command response
└─ no
   ↓
   thread = ensure_current(chat_id)
   ↓
   answerGuestQuery("Думаю…")
   ↓
   GuestEngine.stream(thread.session_dir)
   ↓
   edit same inline_message_id
   ↓
   final edit
```

### Streaming

Guest Mode має одну bubble.

Existing `BubbleProtocol` можна reuse'ити тільки щоб прибрати `<bubble>` markers.

Не використовувати `BubbleComposer`.

Edit cadence:

```text
~0.8–1.0 s maximum frequency
```

Не edit на кожен token.

Final edit обов'язковий навіть якщо останній delta прийшов щойно.

Reuse existing UTF-16-safe Telegram limit logic з `telegram.py`, бажано винести `_fit()` у маленький shared helper, а не дублювати алгоритм. Поточний DM transport уже правильно рахує Telegram 4096 UTF-16 units.

### Failure semantics

Якщо placeholder уже visible:

```text
Luna failure
→ edit same guest message
→ "Сталася помилка..."
```

Ніколи не створювати другу guest reply.

Uncertain `answerGuestQuery` ACK:

```text
do not retry
do not send DM
do not sendMessage
```

---

# Task 4 – Merge Guest Mode into normal Capri poller

Зараз probe запускався окремо. Production більше не повинен вимикати DM mode.

В `app.py`:

```text
router.message       → existing owner DM
router.guest_message → GuestService
```

Polling:

```python
allowed_updates=dp.resolve_used_update_types()
```

Один bot token → один poller.

Startup:

```text
getMe.supports_guest_queries == True
→ guest enabled

False / None
→ warning
→ owner DM все одно запускається
```

Guest failure не повинен валити owner DM service.

### Tests

- `resolve_used_update_types()` містить `message` + `guest_message`;
- owner DM regression працює;
- guest query працює;
- no second poller;
- Guest Mode disabled → DM still starts;
- GuestService startup failure → DM survives, якщо безпечно це ізолювати;
- normal guest query не змінює owner session pointer.

---

# Task 5 – Owner-only thread commands

Commands парсяться **до Luna**.

Для першої версії:

```text
/newthread [optional title]
/threads
/resume <id-or-title>
/title <name>
/status
```

Також можна приймати Hermes-style alias:

```text
/new → /newthread
```

Але canonical назва Capri – `/newthread`.

Hermes теж робить `/new` fresh session, `/resume` existing session, `/sessions` chat-scoped і не auto-expire'ить conversation. [GitHub](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/reference/slash-commands.md?utm_source=chatgpt.com)

### Semantics

`/newthread [title]`

```text
create fresh thread
make current
preserve all old threads
```

`/threads`

```text
current first
then previous by updated_at desc
show:
* a31f0c – ThinkPad vs MacBook (current)
  d9218a – Warsaw trip
```

`/resume <selector>`

```text
bind current guest chat back to selected thread
```

Bare `/resume` → same output as `/threads`.

`/title <name>`

```text
rename current thread
```

`/status`

локально, без Luna:

```text
Thread: a31f0c
Title: ThinkPad vs MacBook
Created: ...
Last active: ...
```

Token/context stats можна додати пізніше.

### Busy semantics

Якщо Luna guest turn уже running:

- `/threads` і `/status` можна дозволити;
- `/newthread`, `/resume`, `/title` – відповісти “зачекай завершення поточної відповіді”.

Не switch session mid-turn.

Hermes робить так само для session switching, бо перемикання session під active turn може записати continuation не туди. [GitHub](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/reference/slash-commands.md?utm_source=chatgpt.com)

### Authorization

Всі ці commands:

```text
paired owner only
```

Non-owner:

```text
zero Luna
zero store mutation
zero thread listing
```

---

# Task 6 – Reference context

Підтримати текст/caption повідомлення, на яке owner reply'нув при summon.

Prompt:

```text
current owner query
+
current Telegram reference
+
persistent OMP thread history
```

Але не:

```text
group history
participant list
owner DM context
other guest chats
```

Reference data не записувати окремо – воно природно потрапить у OMP transcript як частина поточного user turn.

Tests:

- text reply included;
- caption included;
- absent reference works;
- unsupported media ignored;
- reference from one summon becomes part of persistent thread history;
- command message не відправляється Luna.

---

# Task 7 – Live acceptance

Не робити один величезний “works” тест. Перевірити окремі invariants.

### A. Normal DM regression

Після production integration:

```text
owner → Capri DM
```

має працювати так само, як до Guest Mode.

### B. Persistent G1

У human chat, де Capri не member:

```text
@Capriompbot Запам'ятай: варіант A – ThinkPad T14 Gen 3...
```

потім окремий summon:

```text
@Capriompbot Варіант B – MacBook Air M1...
```

потім:

```text
@Capriompbot порівняй два варіанти, про які ми говорили
```

PASS тільки якщо третій turn реально бачить A+B без повторення даних.

Також записати OMP evidence:

```text
same guest chat
same Capri thread id
same session directory
resumed=True on later invocation
```

### C. Web continuity

Turn 1:

```text
знайди актуальну інформацію про X
```

Turn 2:

```text
тепер знайди Y
```

Turn 3:

```text
порівняй те, що ти знайшла
```

Підтвердити actual `web_search` tool execution.

### D. `/newthread`

```text
@Capriompbot /newthread Camera search
```

Потім питання:

```text
що ми щойно порівнювали?
```

Новий thread **не повинен мати старий transcript**.

### E. `/resume`

```text
@Capriompbot /threads
@Capriompbot /resume <old>
```

Після resume:

```text
що ми порівнювали?
```

Старий context повертається.

### F. Owner isolation

До acceptance зберегти:

```text
owner session.json
owner session file hash/mtime
```

Після всіх guest turns вони мають бути unchanged, крім випадків, коли паралельно реально використовувався owner DM.

### G. Same-message delivery

Кожна Luna guest відповідь:

```text
1 × answerGuestQuery
N × editMessageText same inline_message_id
0 × sendMessage
```

---

# Task 8 – Full verification

```powershell
& $py -m pytest tests/test_guest_threads.py -q
& $py -m pytest tests/test_guest_engine.py -q
& $py -m pytest tests/test_guest.py -q
& $py -m pytest -q
git diff --check
```

Очікування:

```text
existing 102 tests + all new tests PASS
```

Після live acceptance записати evidence в:

```text
docs/verification/guest-luna-threads.md
```

Без commit/push.

---
