> Tasks 4–6 are superseded by [the simplified clean-machine bootstrap plan](2026-10-27-clean-machine-bootstrap.md). Earlier implementation/evidence remains historical context.

# Vendored OMP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Execution method is not selected by this document. GPT-6 Astra must not be used for subagents.

**Goal:** Один checkout Capri містить OMP source/SDK та збирає власний Windows x64 runtime; сесії, auth і керований runtime state залишаються в ignored data directory.

**Architecture:** Повний snapshot OMP 18.12.6 з точного чинного commit у `vendor/omp/`, зі збереженням RPC boundary. Capri встановлює SDK локально, окремий build script збирає native addon та executable, а спільне environment задає приватні data/cache paths. Чинні owner і Guest session paths зберігаються.

**Tech Stack:** Windows x64; Python `>=3.14,<3.15`; aiogram 3.31.0; setuptools; офіційний vendored omp-rpc 0.1.0; Bun workspace; Rust `nightly-2026-10-06`; MSVC; pytest; PowerShell; GitHub Actions.

**Spec:** [2026-10-26-vendored-omp-design.md](../specs/2026-10-26-vendored-omp-design.md).

Статус: дизайн погоджено 2026-10-27; standalone Task 1 proof пройшов native build,
exe build та RPC/native smoke. Evidence: `docs/verification/vendored-omp.md`;
toolchain: `runtime-toolchain.json`. Task 2 завершив snapshot/local SDK import.
Переключення executable, заміна running bot і Tasks 3–6 ще не починалися.
Task 1 включає мінімальний реальний RPC prompt та
native tool smoke за останнім уточненням користувача.

## Global Constraints

- OMP baseline: `45c35e40c46166dc726ccc52f5d27f40f2449f99`, version `18.12.6`.
- Source ZIP SHA-256: `a8bbb85ede151ed58c100e84e6d239ca835937e04a51cd287049a9ff737fd4e2`.
- Python `>=3.14,<3.15`; aiogram `3.31.0`; SDK `0.1.0` із vendored source.
- Bun exact version обирається й фіксується у Task 1; upstream floor `>=1.4`.
- Rust `nightly-2026-10-06`; native Windows x64 build через Cargo/N-API/MSVC.
- Snapshot повний; відмінності fork перелічені окремо; upstream notices збережені.
- Немає global OMP, `bun setup`/link/publish, upstream auto-update чи fallback download.
- Default runtime `<data>/bin/omp.exe`; default data `.runtime`; explicit `--omp` збережений.
- Не переносити/скидати pairing, auth, owner sessions, Guest index/sessions, permission config.
- Зберегти Luna, owner tools/approvals/activity, Guest web-only, steering, stop/teardown semantics.
- Не змінювати personality/prompt; не вирізати workspace й не оновлювати OMP.
- Реєстри сторонніх залежностей дозволені; offline/bit-for-bit reproducibility не заявляємо.
- Токени, auth, transcripts, traces, builds і caches не потрапляють у Git.

## Review Focus

1. Fresh clone без глобального OMP і прогрітих native caches: працює справжній локальний RPC runtime — Task 6.
2. Збірка впала або `.exe` зайнятий: попередній artifact та приватний state збережені — Task 4.
3. `--data`, `--omp`, пробіли/Unicode у paths: усі дочірні процеси отримують узгоджені абсолютні paths — Tasks 3–5.
4. SDK з тим самим `0.1.0`, але іншого походження: supported bootstrap установлює саме vendored source — Task 2.
5. Restart і owner↔Guest handoff: жодного reset session/config або паралельного child після unconfirmed teardown — Tasks 5–6.

## File Structure

| Шлях | Відповідальність |
|---|---|
| `vendor/omp/`, `vendor/omp/UPSTREAM.md` | Повний OMP source та опис baseline/local patches |
| `vendor/omp-source-manifest.json`, `scripts/verify-vendor.py` | Перевірка байтової provenance, відсутніх/зайвих source files і дозволених patches |
| `.gitignore`, `.gitattributes` | Приватні/generated paths та стабільні source bytes |
| `runtime-toolchain.json` | Exact перевірені build versions/target/flags |
| `requirements-runtime.txt`, `pyproject.toml`, `requirements-test.txt` | Локальний SDK і Python dependency installation |
| `scripts/bootstrap.ps1`, `scripts/build-runtime.ps1` | Bootstrap та безпечна локальна збірка |
| `scripts/smoke-runtime.py` | Реальний auth-free CLI/RPC lifecycle probe |
| `src/capri/config.py`, `src/capri/cli.py` | Environment та explicit runtime path selection |
| `tests/test_vendor.py`, `tests/test_install.py`, `tests/test_runtime_build.py` | Provenance/install/build wrapper перевірки |
| `tests/test_config.py`, `tests/test_cli.py`, наявні engine/Guest/permission tests | Path/environment/persistence regressions |
| `.github/workflows/test.yml`, `.github/workflows/runtime.yml` | Швидкі Python checks та окремий source-build gate |
| `README.md`, `AGENTS.md`, `docs/verification/vendored-omp.md` | Підтримувані команди, evidence і практичні межі |

## Task 1: Довести Windows source-build path і зафіксувати toolchain

**Files:** Create `runtime-toolchain.json`, `docs/verification/vendored-omp.md`;
scratch лише під `.runtime/vendor-spike/`. Product source ще не змінювати.

**Interfaces:** Produces toolchain manifest з exact Bun/Rust/MSVC/Windows SDK/CMake/Ninja
versions, `platform=win32`, `arch=x64`, Bun target `bun-windows-x64-baseline`,
native ISA baseline, Cargo profile та відтворюваною послідовністю команд.

- [x] Отримати exact source archive в ignored scratch, перевірити SHA-256 до extraction;
  відхилити mismatch. Використати повний archive, а не нинішню часткову SDK extraction.
- [x] Інвентаризувати toolchain. Вибрати один exact Bun `>=1.4` і перевірити
  Rust `nightly-2026-10-06`, VS C++/Windows SDK, CMake/Ninja. Записати реально
  потрібні додаткові tools; відсутні prerequisites повинні давати зрозумілу помилку.
- [x] У чистому scratch виконати `bun install --frozen-lockfile`,
  `bun run build:native`,
  `bun scripts/ci-release-build-binaries.ts --targets win32-x64`.
  Не запускати upstream `setup`, root workspace build або global link.
- [x] Перевірити native ISA: поточний `build-bindings.ts` обирає AVX2 автоматично.
  Додати мінімальний baseline override через shared `scripts/host-detect.ts`
  та `PI_NATIVE_VARIANT=baseline`,
  із тестом у vendored native build tests у Task 4; перевірити фактичний artifact.
  Якщо потрібна зміна source для build, записати точний patch, не змінювати pin.
- [x] З'ясувати Cargo locked invocation для N-API runner, встановити profile `ci`,
  виключити успадковані `RUSTFLAGS`/features, що змінюють ISA; жоден lockfile не змінюється.
- [x] Запустити candidate `--version`, `--help`, `--smoke-test` з isolated test root.
  Встановити SDK candidate в scratch venv; через нього перевірити RPC `get_state`,
  мінімальний реальний prompt і native tool smoke-test, потім confirmed `stop()`.
  Використовувати ізольований test state; жодної інтеграції Capri, Telegram sends,
  зміни робочих session pointers або running bot. Auth та сирі traces тільки ignored.
- [x] Записати точні commands, versions, patches, durations, artifact size/hash,
  outputs і residual network downloads без secrets у manifest/evidence.
  Документи залишені для review; commit/push у цьому spike не виконувалися.

Task 1 call: approved throwaway spike виконувався в ignored scratch без Capri
integration і без production TDD cycle. Два build-only patches треба перенести з
регресійними тестами у Task 4. Short TEMP/TMP потрібен для Windows Unix socket
path limit; arbitrary long checkout paths залишаються окремою перевіркою.

**Gate:** Успішний повтор у порожньому build directory без downloaded OMP exe/native
leaf artifacts. Якщо Windows host route не збирається, спершу усунути конкретну
build-проблему; не видавати prebuilt OMP download за завершення цієї задачі.

## Task 2: Імпортувати snapshot і встановлювати SDK із checkout

**Files:** Create `vendor/omp/`, `vendor/omp-source-manifest.json`,
`scripts/verify-vendor.py`, `requirements-runtime.txt`, `tests/test_vendor.py`,
`tests/test_install.py`; modify `.gitignore`, `.gitattributes`, `pyproject.toml`,
`requirements-test.txt`.

**Interfaces:** `verify-vendor.py --root <checkout>` → exit 0 тільки для цілого
baseline + перелічених local patches; manifest містить upstream SHA та map
archive-relative path → SHA-256. Local requirements явно містить
`./vendor/omp/sdk/python/omp-rpc` та `-e .`; Python dependency — `omp-rpc==0.1.0`.

- [x] RED: vendor tests перевіряють exact commit/hash, LICENSE/notices, source/lockfiles
  на місці; altered/missing/extra fixture file дає failure; дозволений fork patch
  приймається лише за recorded current hash. Тестувати verifier на малих fixtures.
- [x] Запустити `.venv/Scripts/python -m pytest tests/test_vendor.py -q` → очікуваний FAIL.
- [x] Імпортувати весь snapshot із verified archive, з dotfiles/build metadata,
  без nested `.git`. Додати UPSTREAM, manifest, byte-preserving attributes та verifier.
  Зберегти provenance patches із Task 1 окремо від pristine hashes.
- [x] Перевірити `git check-ignore --no-index` для representative runtime/build/cache
  paths: `.runtime/`, `.venv/`, vendor `node_modules/`, `target/`, `dist/`, binaries,
  native `.build/`, generated assets. Source `native/index.js`, fixtures і lockfiles
  не мають губитися. Не приховувати source загальними extension-based patterns.
- [x] RED: fresh-venv install test перевіряє `omp_rpc` distribution direct_url
  на `vendor/omp/sdk/python/omp-rpc`; metadata більше не містить GitHub source URL.
  Перевірити checkout path із пробілами та Unicode, запустивши install із root.
- [x] Перевести dependency/requirements на описаний local source path. У supported
  install явний SDK candidate обов'язковий; `pip install -e .` окремо не рекомендувати.
  Install test використовує локальні wheels/cache для сторонніх dependencies,
  щоб не прийняти network fallback за local SDK success.
- [x] GREEN: vendor/install tests, `python -m pip check`, verifier;
  перевірити `git ls-files .runtime .venv` → empty. Commit snapshot/install change.

## Task 3: Локалізувати OMP root state та узгодити subprocess environment

**Files:** Modify `src/capri/config.py`, vendored `packages/utils/src/dirs.ts`;
create `vendor/omp/packages/utils/test/capri-dirs.test.ts`; modify
`tests/test_config.py`, engine/Guest/permission tests, `vendor/omp/UPSTREAM.md`
і patch records.

**Interfaces:** Зберегти `omp_environment(data: Path) -> dict[str, str]`.
Додати абсолютні `CAPRI_OMP_ROOT=<data>/omp-root`,
`PI_NATIVES_DIR=<data>/cache/natives`, `TMP`/`TEMP=<data>/tmp`;
залишити `PI_CODING_AGENT_DIR=<data>/agent`, blank OMP/PI profiles.
Vendored `getBaseConfigRoot(): string` поважає absolute `CAPRI_OMP_ROOT`,
відхиляє непорожній relative override, без override зберігає upstream semantics.

- [ ] RED: path tests для override absent/absolute/relative, Windows spaces/Unicode;
  owner, Guest та `config get/set` отримують однакові root/native/temp paths;
  успадковані profiles не змінюють їх; HOME/USERPROFILE лишаються справжніми.
- [ ] Запустити focused Python tests і vendored `capri-dirs.test.ts` → FAIL за
  відсутнім hook/local cache behavior, а не через зламаний test harness.
- [ ] Реалізувати мінімальний root hook і shared environment, створення temp/cache dirs
  перед child startup. Оновити documented patch hashes.
- [ ] Audit source і real scratch filesystem diff: auth, logs/stats/models/native
  extraction, on-demand packages, update checks. Для supported startup/config/RPC
  прибрати home-based durable writes та upstream self-update; додаткові конкретні
  patches вписати в UPSTREAM і покрити їхніми focused tests.
- [ ] Записати mapping усіх audited paths. Старий домашній state не переносити
  автоматично; потрібний чинній сесії home-only state спершу визначити й зберегти
  окремо, без secrets у evidence. Agent auth/config/session paths зберігаються.
- [ ] GREEN: focused tests, real auth-free path probe, verifier. Commit isolation change.

## Task 4: Build/bootstrap scripts із promotion тільки перевіреного artifact

**Files:** Create `scripts/bootstrap.ps1`, `scripts/build-runtime.ps1`,
`scripts/smoke-runtime.py`, `tests/test_runtime_build.py`; modify native
`build-bindings.ts` і додати `packages/natives/test/capri-build.test.ts`;
оновити patch metadata.

**Interfaces:** `bootstrap.ps1 [-Data <Path>] [-SkipRuntimeBuild]` створює `.venv`,
встановлює `requirements-test.txt`, перевіряє SDK origin, викликає build за замовчуванням.
`build-runtime.ps1 [-Data <Path>]` збирає тільки win32-x64, повертає nonzero при failure.
`smoke-runtime.py --omp <exe> --data <scratch>` повертає 0 після CLI/RPC lifecycle
та confirmed teardown. Жодних model prompts/Telegram/auth copy.

- [ ] RED: script tests через stub tools у tmp checkout: wrong/missing tool version,
  frozen install failure, native failure, binary build failure, smoke failure,
  occupied destination exe, interrupted promotion. Sentinel old exe і synthetic
  auth/session/config bytes мають лишитися незмінними при failure.
- [ ] RED: native build baseline test перевіряє, що AVX2 host із
  `PI_NATIVE_VARIANT=baseline` створює baseline filename/flags; inherited RUSTFLAGS
  не перетворює його на host-specific artifact. Baseline patch із Task 1 оформити тут.
- [ ] Запустити focused tests → FAIL; реалізувати scripts за validated Task 1 recipe.
  Resolve checkout через `$PSScriptRoot`, tools/paths передавати argument arrays,
  перевіряти `$LASTEXITCODE` після кожного native command; env відновлювати у `finally`.
- [ ] Build читає toolchain manifest, ставить Bun/Cargo caches під `<data>/cache`,
  target/intermediates під `<data>/build`, temp під `<data>/tmp`; install у vendor
  workspace не створює global links. Мінімально доповнити Cargo runner для locked
  install, якщо Task 1 довів потребу, і перевірити lockfile hashes після build.
- [ ] Candidate копіюється до staging у `<data>/bin`, проходить smoke; лише тоді
  replacement final exe. Записати `runtime-build.json`: upstream/source/patch/lock
  hashes, tool versions, target/profile/ISA, candidate SHA-256. Promotion failure
  не змінює старий exe, не чіпає sessions і не завершує running bot.
- [ ] GREEN: stubbed failure tests, vendor Bun tests та реальна збірка/smoke;
  повторний запуск не скидає synthetic state. Commit build scripts.

## Task 5: Переключити CLI та довести persistence regression tests

**Files:** Modify `src/capri/cli.py`, `tests/test_cli.py`, `tests/test_config.py`,
`tests/test_engine.py`, `tests/test_guest_engine.py`, `tests/test_permission.py`.

**Interfaces:** CLI `--omp` default стає `None`; обчислений executable —
`args.omp.resolve()` або `(args.data.resolve() / 'bin/omp.exe')`.
Сигнатури Engine/GuestEngine/app.run не змінюються.

- [ ] RED: CLI tests для default, custom `--data`, explicit absolute/relative `--omp`,
  spaces/Unicode, missing local runtime; fake global `omp` у PATH не викликається.
  Missing binary дає інструкцію build/`--omp` до Telegram startup. Guest probe
  продовжує працювати без runtime binary.
- [ ] RED: synthetic owner session pointer, agent config/auth marker і Guest index
  переживають switch/restart; resume arguments зберігають ті самі paths. Перевірити
  owner→Guest→owner handoff, web-only Guest, native permission config persistence
  та відмову запускати нового child після unconfirmed teardown.
- [ ] Запустити focused tests → FAIL за new expected default/behavior;
  використати наявні SDK fakes, не запускати real account.
- [ ] Реалізувати runtime resolution/missing artifact error. Якщо нові assertions
  вже проходять для engine/storage, залишити цю product logic без змін.
- [ ] GREEN: `.venv/Scripts/python -m pytest tests/test_cli.py tests/test_config.py tests/test_engine.py tests/test_guest_engine.py tests/test_permission.py tests/test_teardown.py -q`.
  Commit runtime switch.

## Task 6: Clean-checkout CI, документація і окреме live приймання

**Files:** Modify `.github/workflows/test.yml`, `README.md`, `AGENTS.md`;
create `.github/workflows/runtime.yml`; finalize `docs/verification/vendored-omp.md`.

**Interfaces:** Швидкий Windows Python job встановлює local SDK без OMP build.
Окремий Windows source-build job збирає candidate й запускає auth-free smoke.
Cold-cache build можна відтворити через workflow_dispatch без cache restore;
перед першим merge потрібен саме cold build, не лише cached success.

- [ ] Оновити Python install job на local requirements; перевірити direct_url provenance,
  весь pytest suite, `pip check` і verifier. Vendor source import commit не має
  провалювати whitespace check лише через вже наявний upstream whitespace:
  зафіксувати pristine exception на baseline, перевіряти власні patches/Capri changes.
- [ ] Додати Windows x64 job із exact toolchain із manifest, pinned action SHAs,
  достатнім окремим timeout і read-only permissions. Ніяких downloads готового OMP
  чи native leaf artifact з upstream. Caches keyed за toolchain/source/locks/patches;
  перший acceptance run з порожніми caches.
- [ ] У fresh clone виконати bootstrap/build. В окремому smoke step забрати OMP
  із PATH, не підкладати `.runtime/source`/старий exe/home native cache і перевірити
  `--version`, config CLI get/set у synthetic root, реальний SDK `get_state`,
  нову/повторно відкриту synthetic session і `stop() is True` без inference.
  Build job може мати Bun/Rust у PATH; smoke не повинен потребувати Bun runtime.
- [ ] Окремий negative dependency gate: середовище без global `omp`, без старого
  `~/.omp`, без cache restore vendored build та без GitHub/codeload/release downloads
  `oh-my-pi` source/binary/SDK. Прямо перевірити ці передумови й заборонити upstream
  downloads для bootstrap/build/tests/smoke; registry dependencies залишаються дозволені.
  Лише після цього виконати checkout Capri → bootstrap → build → tests → local RPC smoke.
- [ ] Перевірити Windows paths із spaces/Unicode. Після build verifier і `git status`
  підтверджують відсутність незадокументованих tracked змін; build не має міняти
  upstream tracked generated bindings без поясненого patch або відновлення exact bytes.
- [ ] README/AGENTS описують bootstrap, prerequisites, local login з тим самим
  environment, rebuild, `--data`, explicit rollback `--omp`, session/cache map,
  dependency/online межі. Старі verification reports лишаються історичною evidence.
- [ ] Запустити `.venv/Scripts/python -m pytest -q`, `python -m pip check`, verifier
  і scoped `git diff --check`; записати реальні результати, clean-build evidence
  та known limits. Commit CI/docs; незалежно перевірити весь change перед merge.
- [ ] Перед live switch зупинити poller/child штатно, створити ignored backup state.
  Після окремо авторизованого запуску перевірити owner resume, bubbles/activity,
  steering/`/stop`, `/permission` + Once/Session/Deny, Guest new/resume та handoff.
  Не робити зовнішні Telegram sends у CI. Без live run залишити цей пункт pending.

## Критерій завершення

У tracked Capri є повний pinned source і SDK; supported bootstrap не отримує OMP
source/binary/SDK з upstream. Fresh Windows checkout збирає і запускає власний
native/RPC runtime, owner/Guest state збережений, керований state локальний,
private artifacts ignored. Build/automated PASS і manual live PASS записані окремо.

Порядок виконання послідовний: **build feasibility → vendor/install → paths →
build wrapper → CLI/persistence → clean CI/live acceptance**. Найбільша невизначеність
зараз — Windows native build; її закриває перший gate до перемикання робочого Capri.
