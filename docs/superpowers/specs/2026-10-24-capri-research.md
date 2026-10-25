# Capri: research ledger

Дата перевірки: 2026-10-24. Метод: офіційна документація, читання вихідного коду через GitHub, read-only запити npm/PyPI та build API. Жодних інсталяцій, OAuth-входів, запитів до моделі чи Telegram-відправлень не виконано. Cached preview попередньої розмови використано лише як контекст; повні вимоги прочитано з наданого вкладення.

## Що підтверджено

| Підсистема | Перевірене джерело / реалізація | Використати напряму | Власна робота Capri |
|---|---|---|---|
| Python → OMP | [офіційний SDK](https://github.com/can1357/oh-my-pi/blob/45c35e40c46166dc726ccc52f5d27f40f2449f99/sdk/python/omp-rpc/README.md), [RPC](https://github.com/can1357/oh-my-pi/blob/45c35e40c46166dc726ccc52f5d27f40f2449f99/docs/rpc.md) | `RpcClient`, typed events, sessions, host tools, login, abort | asyncio adapter, lifecycle, turn correlation |
| OAuth | [OMP implementation](https://github.com/can1357/oh-my-pi/blob/0b5c27ab24719c86a5986b95ee55f4e75bc1aaa0/packages/ai/src/registry/oauth/openai-codex.ts), [OpenAI authentication](https://learn.chatgpt.com/docs/auth) | OMP login та refresh | локальний onboarding; не реалізовувати OAuth |
| Модель | [OpenAI models](https://learn.chatgpt.com/docs/models) | requested model `gpt-6-luna` | перевірка доступності в authenticated OMP catalog, без тихої заміни |
| Web | [OMP Codex search](https://github.com/can1357/oh-my-pi/blob/0b5c27ab24719c86a5986b95ee55f4e75bc1aaa0/packages/coding-agent/src/web/search/providers/codex.ts), [selection](https://github.com/can1357/oh-my-pi/blob/0b5c27ab24719c86a5986b95ee55f4e75bc1aaa0/packages/coding-agent/src/web/search/index.ts) | harness search/fetch | ввімкнути, перевірити джерела та факт пошуку |
| Drafts | [Telegram](https://core.telegram.org/bots/api#sendmessagedraft), [aiogram wrapper](https://docs.aiogram.dev/en/latest/api/methods/send_message_draft.html) | Bot API / aiogram | cadence, commit bubbles, cancellation |
| Guest | [Telegram feature](https://core.telegram.org/bots/features#guest-bots), [aiogram method](https://docs.aiogram.dev/en/latest/api/methods/answer_guest_query.html) | dedicated update + result API | isolated context, authorization, timeout |
| Stickers/reactions/media | [aiogram API](https://docs.aiogram.dev/en/latest/), [Telegram reactions](https://core.telegram.org/bots/api#setmessagereaction) | aiogram methods | semantic aliases, capability checks, file lifecycle |
| Timers/proactivity | [nanobot cron source](https://github.com/HKUDS/nanobot/blob/f4aacdbec2785549c89f0abce60759555e21779b/nanobot/cron/service.py), [Telegram source](https://github.com/HKUDS/nanobot/blob/f4aacdbec2785549c89f0abce60759555e21779b/nanobot/channels/telegram/runtime.py) | pattern: durable jobs bound to destination/session | маленький SQLite scheduler; не підключати другий agent harness |
| Chunking | [OpenClaw streaming design](https://github.com/openclaw/openclaw/blob/main/docs/concepts/streaming.md) | pattern: preview окремо від durable blocks, coalescing | невеликий Python composer; не порт усього gateway |
| Python installation | [uv installation](https://docs.astral.sh/uv/getting-started/installation/), [managed Python](https://docs.astral.sh/uv/guides/install-python/) | standalone uv, managed Python | Node launcher, pinned manifests, recovery |
| JS host → Python bootstrap | [Microsoft uv installer implementation](https://github.com/microsoft/vscode-python-environments/blob/main/src/managers/builtin/uvPythonInstaller.ts) | pattern: resolve installed executable by absolute path | npm CLI-specific bootstrap; готового перевіреного drop-in для Capri не знайдено |
| OMP installation | [official installer](https://github.com/can1357/oh-my-pi/blob/0b5c27ab24719c86a5986b95ee55f4e75bc1aaa0/scripts/install.ps1), [npm metadata](https://registry.npmjs.org/@oh-my-pi%2Fpi-coding-agent/latest) | готовий binary або Bun package | app-private cache, checksums, compatibility probe |

## Точні результати перевірки пакетів

- npm `@oh-my-pi/pi-coding-agent/latest`: `18.12.6`, bin `dist/cli.js`, `engines.bun >=1.3.14`. npm сам не забезпечує Bun runtime.
- OMP main на момент читання: `0b5c27ab24719c86a5986b95ee55f4e75bc1aaa0`. Це не commit опублікованого binary.
- [Build metadata Windows x64 18.12.6](https://build.stencil.so/api/products/omp/versions/18.12.6/windows-x86_64): commit `45c35e40c46166dc726ccc52f5d27f40f2449f99`, `omp-windows-x64.exe`, 224254976 bytes, SHA-256 `73d73c11dc8821cf939441a964992aefc9c5b0d5a4418e9e8985a46439b60eef`. Binary не завантажувався й не запускався.
- Python SDK є під `sdk/python/omp-rpc/` і в цьому release commit. Старий шлях `python/omp-rpc/README.md` повертає 404: попередня розмова та пошуковий кеш мають застаріле посилання.
- SDK metadata: `omp-rpc 0.1.0`, Python `>=3.11`; [PyPI lookup](https://pypi.org/pypi/omp-rpc/json) повернув 404. Тому не покладатися на `pip install omp-rpc`. Пакувати wheel з точного release commit на build CI, включати MIT license/provenance.
- [aiogram metadata](https://pypi.org/pypi/aiogram/json): `3.31.0`, Python `>=3.10,<3.15`. Python 3.14 входить у діапазон; це ще не доказ наявності всіх потрібних Windows wheels та працездатності.
- [uv metadata](https://pypi.org/pypi/uv/json): `0.13.5`. Це кандидат для pin, а не перевірений Capri runtime.

## Наслідки для дизайну

1. Native draft — ephemeral preview з окремим persist через `sendMessage`; він не перетворюється сам на durable message. Поточний draft показує лише незбережений хвіст, інакше вже відправлений текст дублюватиметься.
2. Guest query має одну відповідь і не надає загальної історії чату. Не використовувати звичайний `sendMessage(chat_id)` для guest destination: Telegram попереджає про можливий збіг ID з іншими bot chats. Жодного fallback у owner DM.
3. aiogram уже обгортає `answerGuestQuery`, `sendMessageDraft`, включно з stop parameters. Не потрібен власний Telegram HTTP client.
4. SDK синхронний: reader threads, blocking commands, окремі host-tool threads. Callback має лише передати подію в asyncio loop; виклик blocking RPC із reader callback може заблокувати отримання відповіді. Capri потрібен тонкий concurrency adapter, не новий wire client.
5. OMP пошук має subscription-backed Codex provider. Вихідний код відмовляється вважати completion без search event успішним пошуком. Selection також може обрати дешевшу web-модель. Не обіцяти, що кожен search виконує саме Luna; зафіксувати фактичний provider/model у spike.
6. OpenClaw — корисний reference, але широкий framework. Його chunker може закривати/відкривати fences при вимушеному split; це не відповідає Capri-вимозі «не ділити code block». Capri має відправляти oversized block окремим файлом.
7. nanobot показує destination-bound durable automation і обробку ambiguous delivery. Його agent loop, provider layer та весь gateway не потрібні Capri.
8. uv може сам завантажити Python; лишається bootstrapping самого uv. Не виконувати довільний remote install script і не залежати від PATH, який installer не може змінити у вже запущеного parent process.
9. npm lifecycle hooks не можна вважати гарантованими: [npm scripts](https://docs.npmjs.com/cli/v11/using-npm/scripts/). Потрібен той самий idempotent bootstrap при першому `capri` запуску. Встановлення потребує мережі й доступного user cache.

## Що ще не доведено — обов'язкові spikes після схвалення

| Spike | Питання | Умова проходження / рішення при невдачі |
|---|---|---|
| S0 distribution | binary та matching SDK працюють без global OMP/Bun/Python/uv? | fresh Windows VM: version, RPC ready, host tool roundtrip; інакше оцінити app-local Bun + npm OMP |
| S1 auth/model/web | account надає Luna, OAuth працює, search має grounding? | local login, catalog selection, streamed answer, search trace + URLs; при невдачі блокувати обіцянку subscription-only |
| S2 Telegram drafts | кілька draft → final → next draft не мерехтять/дублюються? | записаний live trace + ручна перевірка Telegram mobile/desktop, interruption/429 |
| S3 Guest | які реальні query lifetime, context fields, підтримка клієнтів? | BotFather enable + owner summon з reply у чужому chat, один результат; timeout виміряти, не вигадувати API SLA |
| S4 policy isolation | tools/config discovery ізольовані від user/workspace OMP? | запис effective tool set і тест malicious guest request без shell/files/memory access |
| S5 media | Luna приймає images через цей provider? | справжній screenshot з описом видимих деталей; відсутність vision не підміняти успіхом text-only |

Це дослідження підтверджує наявність будівельних блоків, а не працездатність готового Capri. Жодні live acceptance checks зараз не пройдені.
