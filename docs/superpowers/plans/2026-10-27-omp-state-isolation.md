# Task 3: ізоляція OMP state — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Направити керований OMP runtime state у приватний data directory Capri й перевірити це без переключення production executable.

**Architecture:** Зберегти спільний `omp_environment(data: Path) -> dict[str, str]` для owner, Guest і permission CLI. Мінімальний documented patch у vendored OMP додає абсолютний `CAPRI_OMP_ROOT`; чинні agent/session paths зберігаються. Окремий source-based filesystem probe перевіряє змінений код до майбутнього build/runtime switch.

**Tech Stack:** Windows x64, Python 3.14, pytest, vendored OMP 18.12.6, Bun 1.4.4 з перевіреного `runtime-toolchain.json`.

**Spec:** `docs/superpowers/specs/2026-10-26-vendored-omp-design.md`, розділ «Локальні дані та зміна runtime path»; деталізація Task 3 з `docs/superpowers/plans/2026-10-26-vendored-omp.md`.

Підстава: розмова «Запропонована наступна ітерація», ID `6adf8f23-b238-83eb-8d00-33b8a20540f3`, і поточний HEAD `c313984`. Це план реалізації, а не звіт про виконані тести.

## Global Constraints

- Виконати лише Task 3. Build/bootstrap scripts, promotion artifact і default executable path належать Task 4/5.
- Не застосовувати `vendor/omp-patches/0002-build-proof.patch` у цій задачі.
- Не замінювати `.runtime/omp.exe`, не перезапускати активного бота й не запускати другого Telegram poller.
- Не переносити pairing, auth, permission settings, owner pointer або Guest transcripts; не копіювати домашні caches автоматично.
- Не змінювати `HOME`/`USERPROFILE`; environment overrides застосовуються лише до child processes.
- Не змінювати upstream pin, lockfiles, SDK dependency source, prompts, capabilities чи approval policy.
- Робочий каталог native tools не стає filesystem sandbox. Обіцянка охоплює керований runtime state, а не довільні записи tools.
- Не використовувати GPT-6 Astra для subagents. Цей план передбачає послідовне виконання основним агентом.

## Review Focus

1. Відносний data path має стати абсолютним до запуску child, незалежно від child cwd — тести кроку 1.
2. Успадковані profile/root/native/temp overrides не мають перенаправити Capri у чужий state — кроки 1 і 3.
3. Відсутній або недоступний temp directory не має спричиняти мовчазний fallback у user temp — кроки 1 і 4.
4. Resolver кешує paths; environment tests мають скидати cache або створювати окремий процес — крок 2.
5. Windows drive-relative paths і довгі socket paths потребують явної відмови/зафіксованого обмеження — кроки 2 і 4.

## Контракт шляхів

`data` нормалізується через `Path.resolve()` від cwd виклику. За замовчуванням це `.runtime`, але довільний `--data` має працювати за тією самою схемою.

| Environment key | Значення |
| --- | --- |
| `CAPRI_OMP_ROOT` | `<absolute data>/omp-root` |
| `PI_CODING_AGENT_DIR` | `<absolute data>/agent` |
| `PI_NATIVES_DIR` | `<absolute data>/cache/natives` |
| `TEMP`, `TMP` | `<absolute data>/tmp` |
| `OMP_PROFILE`, `PI_PROFILE` | порожній рядок |
| `PI_CONFIG_DIR` | `.capri-omp`, чинний compatibility fallback для старого executable |

`omp_environment()` повертає лише overrides й створює необхідні каталоги до spawn. Повторний виклик безпечний; `OSError` під час створення каталогу не приховується. `os.environ` батьківського процесу не змінюється. SDK і config CLI успадковують решту environment за чинним механізмом.

`getBaseConfigRoot(): string`: непорожній абсолютний `CAPRI_OMP_ROOT` має пріоритет над home-based root; непорожній relative override кидає помилку з назвою змінної. Пропозиція для точного контракту: обрізати зовнішні пробіли; unset/empty/whitespace означає чинну upstream поведінку; `~`, `C:relative`, `\\relative` на Windows відхиляти, бо це не повністю визначені абсолютні paths. Не додавати підтримку нових ОС.

## Крок 1: Python environment — RED → GREEN

**Files:** Modify `src/capri/config.py`, `tests/test_config.py`.

**Interfaces:** Зберегти `omp_environment(data: Path) -> dict[str, str]`; це єдиний builder overrides для наявних call sites.

- [x] Додати `test_omp_environment_uses_absolute_private_paths`: перевірити всі значення таблиці, включно з `PI_CONFIG_DIR`, і наявність каталогів.
- [x] Додати параметризовані cases для relative path, пробілів і Unicode (`Capri дані`); після зміни cwd перевірити, що повернуті paths залишаються абсолютними.
- [x] Додати `test_omp_environment_does_not_mutate_parent`: задати сторонні profiles/root/native/temp в `monkeypatch`, перевірити overrides і незмінний `os.environ`, відсутність `HOME`/`USERPROFILE` у поверненому словнику.
- [x] Додати cases повторного виклику й file-instead-of-directory для `data/tmp`: очікувати ідемпотентність або `OSError`, без fallback.
- [x] Запустити `.venv/Scripts/python -m pytest tests/test_config.py -q`; підтвердити RED саме через відсутні paths/directories.
- [x] Реалізувати контракт у `omp_environment()` без дублювання його логіки в engines.
- [x] Повторити focused command; усі tests мають пройти.

## Крок 2: Vendored root hook — RED → GREEN

**Files:** Modify `vendor/omp/packages/utils/src/dirs.ts`; create `vendor/omp/packages/utils/test/capri-dirs.test.ts`.

**Interfaces:** Зберегти export `getBaseConfigRoot(): string` і наявні resolver exports. Тести використовують `__resetDirsFromEnvForTests()` за зразком upstream directory tests; invalid import-time env перевіряється окремим child.

- [x] Підготувати workspace dependencies лише за frozen lockfile, якщо вони відсутні. Виконувати Bun commands з `vendor/omp`; не запускати `bun setup`/global links. Native addon має відповідати pin; помилка import/native loading є проблемою harness, а не очікуваним RED.
- [x] Написати assertions: absent/empty override зберігає upstream root; absolute override з пробілами/Unicode задає root; relative/tilde/Windows drive-relative/root-relative значення відхиляються; жодний invalid override не створює home-based root.
- [x] З blank profiles і приватним agent override перевірити root-derived paths: install identity, logs/stats, models/cache, global daemon/session-owner paths. Конкретні exported helpers вибрати з `dirs.ts`; assertion для кожного — path знаходиться в очікуваному data subtree.
- [x] Окремо довести незмінність `getAgentDir()` та owner session directory при новому root. Перевірити profile behavior без Capri override, щоб patch не ламав звичайний upstream режим.
- [x] Запустити `bun test packages/utils/test/capri-dirs.test.ts` → assertion RED через відсутній root hook.
- [x] Додати мінімальний hook перед home fallback. Не переписувати весь `DirResolver`; додаткові обходи root виправляти лише за конкретним failing test/audit evidence.
- [x] Запустити новий test і наявні `dirs.test.ts`, `profiles.test.ts`, `install-id.test.ts`, `natives-dir-override.test.ts` у `packages/utils/test`; очікувати PASS без зміни lockfiles.

## Крок 3: Єдиний environment у всіх launcher paths

**Files:** Modify `tests/test_engine.py`, `tests/test_guest_engine.py`, `tests/test_permission.py`; production call sites `src/capri/engine.py`, `src/capri/guest_engine.py` змінювати лише за потреби.

**Interfaces:** Owner/Guest передають overrides у SDK `env`; native permission CLI передає `{**os.environ, **omp_environment(data), 'NO_COLOR': '1'}` у `subprocess.run`.

- [x] Розширити SDK fake assertions для owner і Guest: усі keys таблиці збігаються для одного data root; каталоги існують уже в момент fake startup.
- [x] У permission subprocess fake окремо перевірити `config get` і `config set`: ті самі root/native/temp paths, порожні profiles, справжні inherited HOME/USERPROFILE, `NO_COLOR=1`.
- [x] Задати конфліктні inherited overrides в regression tests. Перевірити owner/Guest session paths і чинну web-only Guest isolation без їх перенесення.
- [x] Запустити `.venv/Scripts/python -m pytest tests/test_engine.py tests/test_guest_engine.py tests/test_permission.py -q`; якщо є RED, усунути лише відповідне розходження launcher contract.

## Крок 4: Source audit та реальні filesystem probes

**Files:** Create `scripts/probe-omp-isolation.ts`; extend `docs/verification/vendored-omp.md`. Додаткові production patches допускаються лише для виявленого конкретного запису з regression test.

**Interfaces:** Одноразовий auth-free probe запускається з `vendor/omp` командою `bun ../../scripts/probe-omp-isolation.ts <absolute-scratch-data>`. Imports явно вказують на vendored source. Probe відмовляється використовувати чинний `.runtime/agent` або наявний непорожній data root.

- [x] Перед filesystem probe інвентаризувати source writes: `homedir`, app-data dirs, root helpers, native loader, temp/socket paths, auth/model DB, logs/stats, install identity, package/on-demand installers і update machinery. Для кожного записати resolver, фактичний target і trigger. Ізоляція startup не доводить ізоляцію неактивованого installer.
- [x] Перевірити окремо підтримуваний startup/config/RPC path на self-update/download behavior. Знайдені обходи виправляти підтримуваним override або мінімальним test-backed patch; не вигадувати новий updater/build subsystem.
- [x] Probe створює disposable data tree під ignored `.runtime` та застосовує environment з таблиці до нового процесу до imports. Із source resolver реально створює install ID, перевіряє вибрані root/agent/native/temp paths і виконує auth-free startup/config/RPC smoke настільки, наскільки дозволяє підготовлений source harness. Для RPC child обов'язкове підтверджене завершення.
- [x] Перед/після зняти metadata inventory відомих home-based OMP dirs (`.omp`, `.capri-omp`) та виявлених audit targets; raw auth/config/transcript content не читати у звіт. Для startup probe зафіксувати process file writes, якщо доступний tracer; явно вказати межі спостереження, якщо є лише directory snapshots.
- [x] Повторити path probe для scratch name з пробілами/Unicode. Окремо перевірити короткий `<data>/tmp`; якщо довгий custom `--data` ламає worker socket, зафіксувати відтворення й обмеження без тихого переходу у global temp.
- [x] Записати PASS лише для реально виконаних cases; auth/model-network/on-demand paths, які не активувалися, позначити static-only або pending. Authenticated і compiled-runtime acceptance лишаються наступним задачам.

Старий `.runtime/omp.exe` і Task 1 binary не містять нового hook: їх запуск не є доказом його роботи. Якщо source RPC harness недоступний, Task 3 acceptance неповний; записати конкретну залежність від Task 4, не застосовувати build-proof patch і не оголошувати повну runtime isolation. Source-level resolver/filesystem evidence зберігає самостійну цінність.

## Крок 5: Provenance, документація й фінальна перевірка

**Files:** Create `vendor/omp-patches/0003-state-isolation.patch`; modify `vendor/omp/UPSTREAM.md`, `vendor/omp-source-manifest.json`, `docs/verification/vendored-omp.md`, `README.md`.

- [x] Зберегти original manifest hashes. Записати `dirs.ts` у `patches` з original/current SHA-256; нові vendored tests — у `additions`; patch file — у `records`; оновити hash `UPSTREAM.md`. Не «перебазовувати» baseline hashes під змінений код.
- [x] У `UPSTREAM.md` позначити state-isolation patch APPLIED, build-proof patch залишити NOT APPLIED. README пояснює нові paths і те, що existing executable ще не підтримує новий root hook; не обіцяти завершену binary isolation.
- [x] У verification report записати path mapping, commands/results, межі filesystem audit, pending gates. Не додавати secrets, sessions, raw RPC traces або абсолютні приватні auth paths.
- [x] Запустити `.venv/Scripts/python -m pytest -q` → PASS.
- [x] Запустити focused Bun tests з кроку 2 та source probe з кроку 4 → PASS для заявленого acceptance.
- [x] Запустити `.venv/Scripts/python scripts/verify-vendor.py --root .` і `git diff --check` → exit 0.
- [x] Переглянути diff: lockfiles, Task 4 build sources, executable і приватний runtime не змінилися. Commit лише конкретних reviewed files: `Isolate OMP runtime state under Capri data directory`.

## Готовність і наступний перехід

Task 3 готовий, коли shared environment, vendored hook, launcher regressions, provenance verifier та source filesystem probe проходять, а audit має явний path mapping і чесно окреслене покриття. Це не production runtime switch і не live Telegram acceptance.

Після цього — окремий Task 4: build/bootstrap із baseline ISA, locked dependencies та перевіркою artifact перед promotion. Саме rebuilt binary згодом має повторити isolation probes перед переключенням Capri.

## Implementation notes (2026-10-27)

Виконано за цим планом. Audit-driven additions: BUN_INSTALL_CACHE_DIR=<data>/cache/bun і BUN_RUNTIME_TRANSPILER_CACHE_PATH=<data>/cache/transpiler. Source probe потребує upstream generated tool-view asset і вимкненого parent transpiler cache до запуску; це harness preparation, не Task 4 build wrapper. Evidence, review fix, exact acceptance limits: docs/verification/vendored-omp.md, Task 3.
