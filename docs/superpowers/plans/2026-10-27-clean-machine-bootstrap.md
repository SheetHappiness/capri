> Implementation and actual acceptance status: [verification record](../../verification/vendored-omp.md#clean-machine-bootstrap-a--implementation-and-local-acceptance-2026-10-27). Clean-Windows/newer-system-toolchain/live acceptance have separate pending statuses.

# Clean-machine bootstrap A — Implementation Plan

> **For agentic workers:** Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkboxes for tracking. This is a proposal; product implementation has not started.

**Goal:** На Windows x64 із Git, PowerShell 7 x64, Python 3.14 x64 та потрібними MSVC/Windows SDK одна команда `./scripts/bootstrap.ps1` створює Python environment, встановлює локальні build tools, збирає vendored OMP, перевіряє його й готує Capri до налаштування облікових даних та запуску.

**Architecture:** Bootstrap керує підготовкою, а наявний `build-runtime.ps1` зберігає відповідальність за source verification, build, smoke та встановлення перевіреного executable. Інструменти, кеші та результати належать приватному Data; CLI використовує `<data>/bin/omp.exe`. Складної системи транзакцій немає.

**Tech Stack:** Windows x64, PowerShell 7, Python 3.14, pytest, vendored omp-rpc, Bun 1.4.4, Rust nightly-2026-10-06, MSVC/Windows SDK, CMake, Ninja.

**Spec:** [Погоджений користувачем варіант A](chatgpt-conversation://6adf8f23-b238-83eb-8d00-33b8a20540f3), останні повідомлення прочитані 2026-10-27, із поточним уточненням користувача: сумісні системні MSVC/SDK замість exact pins; простий `.tmp` download без bootstrap concurrency/recovery machinery. Базовий source/isolation design: `docs/superpowers/specs/2026-10-26-vendored-omp-design.md`. Цей план пропонує замінити scope незавершених Tasks 4–6 у `2026-10-26-vendored-omp.md`; попередні записи evidence залишаються історичними.

## Global Constraints

- Системні prerequisites встановлюються вручну: Git; PowerShell 7 x64; Python `>=3.14,<3.15` x64; Visual Studio 2022 C++ Build Tools x64 та сумісний Windows SDK. Новіший сумісний toolset/SDK не відхиляється через відмінність patch version.
- Recorded proof Task 1: MSVC toolset `14.44.35207`, compiler `19.44.35229`, Windows SDK `10.0.26100.0`. Це історичні версії перевіреної збірки, а не обов'язкові pins bootstrap. Кожна нова збірка записує фактично використані MSVC/SDK versions; сумісність підтверджують native/exe build і smoke.
- CMake `4.4.4` і Ninja `1.12.1` також потрібні поточному build. Пропозиція цього плану: bootstrap встановлює їх локально, щоб вони не були додатковими ручними prerequisites.
- Bun `1.4.4`, revision `38afee6c8`, Windows x64 baseline; Rust `nightly-2026-10-06`, host `x86_64-pc-windows-msvc`. Точні значення читаються з `runtime-toolchain.json`.
- Локальний rustup має окремо закріплені installer version, URL і SHA-256. Їх визначення та перевірка є частиною Task 1, без використання `latest` у готовому bootstrap.
- Default Data: `<checkout>/.runtime`; `.venv` завжди належить checkout. Відносний `-Data` рахується від cwd виклику. Checkout визначається через `$PSScriptRoot`.
- Жодного глобального встановлення Bun/Rust/CMake/Ninja, зміни user/machine PATH, UAC або автоматичного встановлення VS/Python. Зміни process environment/cwd відновлюються у `finally`.
- OMP source і SDK беруться лише з `vendor/omp`; OMP release exe чи готовий native addon не підміняють збірку. Завантаження build tools та registry dependencies дозволені.
- Python requirements: `requirements-test.txt` із checkout root; SDK origin перевіряється через `direct_url.json` та шлях до vendored SDK, а не лише `0.1.0`.
- Frozen Bun lockfile, Cargo locked build, baseline ISA та наявні provenance checks зберігаються. Відтворювана процедура не означає гарантовано однаковий SHA-256 executable.
- Auth/session/config, owner pairing і Guest state не переносяться та не скидаються bootstrap. Smoke використовує свіжий scratch без облікових даних, model prompt чи Telegram.
- Поза scope: journals, recovery engine, транзакція exe+JSON, загальний failure-injection framework, нове parallel bootstrap locking, concurrent bootstrap suite, автоматичний запуск/перезапуск бота та автоматичний login. Перша ітерація розрахована на один bootstrap за раз; наявний build lock зберігається.

## Review Focus

1. Встановлений глобальний Bun/Rust неправильної версії: bootstrap використовує свої інструменти — Task 1 tests.
2. Недокачаний `.tmp` або повторний запуск: download починається заново; лише перевірений SHA-256 дозволяє встановлення — один простий retry test у Task 1, state-preservation test у Task 2.
3. Unicode/пробіли та надто довгий Windows socket path: аргументи передаються правильно; непідтримуваний довгий шлях дає діагностику — Tasks 2–3 tests.
4. Smoke failure або зайнятий final exe: старий final exe збережено; running bot не завершується — Task 3 tests.
5. Custom Data та explicit `--omp`: CLI не повертається до `.runtime/omp.exe` чи global `omp` — Task 4 tests.

## Поточна база

- Перевірено checkout на commit `746af9d` (`Add candidate-only vendored OMP build`); перед записом цього плану working tree був чистий.
- `scripts/build-runtime.ps1` уже створює hash-verified source snapshot, збирає native addon/exe й записує `bin/omp.<run-id>.candidate.exe` та `build/<run-id>/candidate-result.json`.
- Цей script вимагає готової `.venv` та доступних build tools; production bootstrap і smoke script відсутні. Він також примусово вибирає exact MSVC/SDK й перевіряє їх рівність manifest: Task 2 прибирає ці runtime requirements, залишаючи історичний proof незмінним.
- `src/capri/cli.py` усе ще має default `.runtime/omp.exe`, незалежний від `--data`.
- У `tests/test_runtime_build.py` уже є майбутні контракти smoke/publication. Не писати другий harness; розділити candidate-specific і final-pipeline assertions згідно з новою поведінкою.
- Старий verification document фіксує незавершені RED contracts. Перед реалізацією отримати свіжий baseline, а не вважати весь suite зеленим.

## File Structure

| File | Відповідальність |
|---|---|
| `runtime-toolchain.json` | Exact versions/downloads керованих tools; MSVC/SDK proof versions — evidence, не required pins |
| `scripts/bootstrap-tools.ps1` | Перевірка, download та підготовка локальних tools |
| `scripts/bootstrap.ps1` | System preflight, `.venv`, local SDK, tools, виклик build |
| `scripts/build-runtime.ps1` | Наявний build плюс smoke і встановлення final exe |
| `scripts/smoke-runtime.py` | Auth-free CLI/worker/RPC lifecycle у свіжому scratch |
| `src/capri/cli.py` | Default `<data>/bin/omp.exe`, діагностика відсутнього runtime |
| `tests/test_bootstrap.py`, `tests/test_runtime_smoke.py` | Нові boundary/regression tests |
| `tests/test_runtime_build.py`, `tests/test_cli.py` | Розширення наявних контрактів |
| `README.md`, `AGENTS.md`, `docs/verification/vendored-omp.md` | Підтримуваний шлях встановлення та фактичне acceptance evidence |

### Task 1: Локальний pinned toolchain

**Interfaces:** `Initialize-CapriTools -Data <absolute-path> -Toolchain <hashtable>` у `scripts/bootstrap-tools.ps1` повертає hashtable абсолютних шляхів `Bun`, `Rustup`, `Rustc`, `Cargo`, `CMake`, `Ninja`, `RustupHome`, `CargoHome`. Helper не змінює PATH викликача; bootstrap налаштовує child environment.

- [ ] RED: у `tests/test_bootstrap.py` додати `test_download_hash_mismatch_is_not_executed`, `test_incomplete_tmp_download_is_downloaded_again`, `test_tools_ignore_global_versions`, `test_tool_setup_preserves_caller_environment`. Download/process boundaries замінити простими локальними fixtures; без окремого interrupted-download framework.
- [ ] Запустити `.venv/Scripts/python -m pytest tests/test_bootstrap.py -q`; отримати очікувані failures на відсутню реалізацію.
- [ ] Додати до manifest офіційні immutable download coordinates та перевірені SHA-256 для Bun baseline, rustup-init, CMake й Ninja. Перевірити доступність exact releases; не підміняти недоступну версію іншою мовчки.
- [ ] Реалізувати мінімальний шлях: download у `.tmp` під приватною tools directory → SHA-256 → extraction у тимчасову директорію → перевірка version → rename у final tool directory. Для rustup перевірений installer запускається лише після hash check, потім встановлюється pinned toolchain. Недокачаний `.tmp` на наступному запуску не відновлюється, а завантажується заново. Жодних journals, resume protocol чи transaction metadata; version mismatch не спричиняє видалення сторонньої директорії.
- [ ] Розмістити Bun у `<data>/tools/bun`, CMake/Ninja у своїх `<data>/tools/` директоріях. Rust: `RUSTUP_HOME=<data>/tools/rust/rustup`, installer `CARGO_HOME=<data>/tools/rust/cargo`; rustup install без зміни user PATH, profile minimal, exact dated toolchain.
- [ ] Узгодити Rust proxies з build: PATH містить `<data>/tools/rust/cargo/bin`, RUSTUP_HOME зберігається в child environment; build надалі використовує власний `<data>/cache/cargo`. Окремий test перевіряє compiler invocation після цієї зміни CARGO_HOME.
- [ ] GREEN: ті самі focused tests; перевірити встановлення реальних pinned tools у новому ignored Data. Commit `Add private pinned bootstrap tools`.

### Task 2: Одна команда bootstrap

**Interfaces:** `scripts/bootstrap.ps1 [-Data <Path>]` повертає success лише після успішного build/smoke/publication. Bootstrap не пропонує skip-build режим у цій ітерації. Виклик build — `& "$PSScriptRoot/build-runtime.ps1" -Data $dataRoot` із перевіркою помилок.

- [ ] RED: `test_missing_system_prerequisites_stop_before_download`, `test_bootstrap_installs_vendored_sdk`, `test_bootstrap_rerun_preserves_private_state`, `test_bootstrap_paths_and_environment`. Assert Windows/Python architecture і version; відсутні VS C++/SDK components у diagnostics; `.venv` у checkout; збережені synthetic state bytes та caller env/cwd.
- [ ] RED: у наявному build harness додати `test_build_accepts_newer_system_toolchain_and_records_actual_versions`: stub сумісного VS 2022 x64 toolset/SDK з іншими versions проходить preflight, а report містить саме ці versions. Missing compiler/SDK і wrong target architecture лишаються помилками. Не оголошувати справжній toolchain сумісним лише на підставі stub test.
- [ ] Запустити focused bootstrap tests → очікуваний RED.
- [ ] Реалізувати preflight для Git, Windows/PowerShell/Python x64 та installed VS 2022 C++ Build Tools x64 із Windows SDK, включно з виявленням VS без Developer shell. Перевіряти доступність x64 compiler/linker та SDK include/lib/tool paths; не вимагати історичних patch versions. Відсутні компоненти показати за назвами й дати команду повторного запуску.
- [ ] У `build-runtime.ps1` прибрати примусові `-vcvars_ver`/`-winsdk` із proof values та exact-equality gates для MSVC/SDK/compiler. Вибирати встановлене середовище VS 2022 x64 із SDK; compiler/toolset/SDK versions читати з фактичного environment та output, записувати у per-run report. Історичні proof values у `runtime-toolchain.json` явно позначити evidence-only, не переписуючи їх як поточні вимоги. Exact Bun/Rust checks залишити.
- [ ] Створити `.venv`, або перевірити version/architecture наявної; несумісну `.venv` не видаляти автоматично. Встановити `requirements-test.txt` із checkout root; перевірити SDK origin та запустити `verify-vendor.py`.
- [ ] Викликати Task 1 helper, налаштувати лише process tools/environment, викликати build. Повторний запуск reuse перевірені tools/caches, а source build використовує свіжий snapshot. Новий bootstrap lock та підтримку одночасного встановлення tools/venv не додавати; наявний build lock не змінювати.
- [ ] При помилці вивести stage і шлях до приватного log; stdout не містить credentials або повного environment. Фінальний текст успіху вказує final executable та наступні ручні token/login кроки.
- [ ] GREEN: focused bootstrap tests і build toolchain-selection/report tests; повторний послідовний запуск із reuse. Concurrent bootstrap suite не входить у цю ітерацію. Commit `Add clean-machine bootstrap entry point`.

### Task 3: Auth-free smoke та просте встановлення exe

**Interfaces:** `scripts/smoke-runtime.py --omp <absolute-exe> --data <fresh-scratch>`: exit 0 лише після CLI, worker, native extraction, RPC `get_state()` та `stop() is True`; записує `smoke-result.json` із candidate SHA-256 і результатами перевірок. `build-runtime.ps1 [-Data <Path>]` розширюється до pipeline build → smoke → publish, final `<data>/bin/omp.exe`.

- [ ] RED: `tests/test_runtime_smoke.py`: `test_smoke_requires_confirmed_stop`, `test_smoke_timeout_fails`, `test_smoke_uses_fresh_private_environment`, `test_smoke_rejects_nonempty_scratch`. Process/SDK fakes перевіряють відсутність prompt/Telegram/login та будь-якого копіювання auth.
- [ ] RED: розширити наявний build harness: `fail_smoke`, `smoke_timeout`, locked destination, changed candidate hash; усі до publication зберігають old final exe та state. Success перевіряє final bytes і smoke до publication. Прибрати лише контракти складних interrupted exe+JSON transactions, якщо такі з'являться.
- [ ] Запустити `.venv/Scripts/python -m pytest tests/test_runtime_smoke.py tests/test_runtime_build.py -q` → очікуваний RED на нову поведінку.
- [ ] Реалізувати CLI `--version`, `--help`, `--smoke-test`, isolated config та RPC lifecycle через vendored SDK. Використати чинний environment builder із `src/capri/config.py`, чистий scratch `<data>/s/<short-id>` і короткий private temp. При надто довгому шляху — пояснити скорочення Data, без global temp fallback.
- [ ] У smoke child PATH забрати global OMP/Bun/Rust; candidate має працювати самостійно. Обмежити час stages; невпевнений teardown не може дати PASS. Перевірити native cache/extraction без готового addon поруч із exe.
- [ ] Після PASS перевірити candidate hash повторно та встановити final через одну Windows file replacement operation на тому самому volume; перше встановлення — rename. Не видаляти final перед move, не завершувати працюючий бот. Locked final дає чітку помилку.
- [ ] Зберегти existing per-run provenance та smoke evidence. Не створювати обов'язковий runtime sidecar або exe+JSON transaction: CLI не залежить від JSON. Звіт після publication не є механізмом recovery.
- [ ] GREEN: focused tests та реальний auth-free candidate smoke із новим scratch. Перевірити default/space/Unicode Data і зрозумілий long-path failure. Commit `Smoke-test and publish the vendored runtime`.

### Task 4: Capri використовує новий local runtime

**Interfaces:** CLI `--omp` default `None`; normal-mode executable = `args.omp.resolve()` або `args.data.resolve() / 'bin/omp.exe'`. Сигнатури engine/Guest/permission не змінюються. Telegram-only `--guest-probe` не вимагає OMP exe.

- [ ] RED: у `tests/test_cli.py` додати default/custom Data, explicit relative/absolute `--omp`, Unicode/spaces, missing exe before Telegram startup та guest-probe без exe. Fake global `omp` не викликається.
- [ ] RED: доповнити наявні engine/Guest/permission tests лише відсутніми assertions: session pointers/config/auth markers зберігаються; owner→Guest→owner, web-only Guest та unconfirmed teardown працюють із новим path.
- [ ] Запустити focused CLI/runtime regression tests → очікуваний RED там, де default ще старий.
- [ ] Реалізувати resolution і missing-file diagnostic із командою bootstrap. Explicit `--omp` зберігає ручний override. Оновити login приклад на `.runtime/bin/omp.exe` з чинним private environment.
- [ ] GREEN: `.venv/Scripts/python -m pytest tests/test_cli.py tests/test_config.py tests/test_engine.py tests/test_guest_engine.py tests/test_permission.py tests/test_teardown.py -q`. Commit `Use the bootstrapped local OMP by default`.

### Task 5: Clean-machine acceptance і документація

**Interfaces:** Підтримуваний user flow: clone → `./scripts/bootstrap.ps1` → manual token/login → `.venv/Scripts/python -m capri.cli`. Auth-free bootstrap acceptance і authenticated Telegram acceptance записуються окремо.

- [ ] Оновити README/AGENTS та позначити старі Tasks 4–6 як superseded цим scope. Описати required VS 2022 C++ x64/compatible SDK окремо від recorded proof versions, Python 3.14 x64, локальні pinned tools, network requirement, короткий Data path та повторний послідовний запуск.
- [ ] Запустити повний `.venv/Scripts/python -m pytest -q`, `.venv/Scripts/python scripts/verify-vendor.py --root .`, `git diff --check`. Новий pipeline має закрити старі RED contracts; невиправлені failures не маскувати xfail/skip.
- [ ] У disposable Windows VM або еквівалентному чистому host підготувати тільки оголошені system prerequisites. Без `.runtime`, `.venv`, готових OMP outputs, user Bun/Rust/CMake/Ninja та credentials виконати fresh clone → bootstrap.
- [ ] Підтвердити local tools, vendored SDK origin, source/lock verification, real native/exe build, smoke і final exe. Записати фактичні MSVC/SDK versions; використати новіший сумісний VS 2022 toolchain, якщо доступний, інакше чесно залишити його реальну acceptance непідтвердженою. Global PATH/user Rust roots не змінюються; process PATH після bootstrap відновлений.
- [ ] Повторити bootstrap з synthetic owner/Guest/config/auth sentinel files; підтвердити byte preservation. Окремо перевірити missing VS prerequisite та download hash mismatch.
- [ ] Записати commands/results/tool versions/hash у `docs/verification/vendored-omp.md` без секретів. Якщо VM недоступна, чесно залишити clean-machine acceptance pending: локальний fresh Data не доводить чисту Windows.
- [ ] Після підготовки runtime провести окремий погоджений live запуск: private login/token, owner reply, Guest reply, `/permission`, `/stop`, restart/session resume. Bootstrap сам не викликає цих дій.
- [ ] Commit `Document and verify clean-machine bootstrap`. Окремий постійний source-build CI workflow можна додати наступною ітерацією; він не блокує цю реалізацію.

## Критерій завершення

На Windows із заявленими системними prerequisites команда `./scripts/bootstrap.ps1` завершується успішно, створює `.venv` і `<data>/bin/omp.exe`, встановлює локальні pinned tools та проходить auth-free smoke. Capri за замовчуванням вибирає саме цей exe. Повторний запуск зберігає приватний state; помилка до встановлення executable зберігає старий final. Live Telegram/model acceptance має окремий фактичний статус.

## Офіційні технічні опори

- [Rustup: локальне розміщення через CARGO_HOME/RUSTUP_HOME](https://rust-lang.github.io/rustup/installation/index.html#choosing-where-to-install).
- [Rustup environment variables](https://rust-lang.github.io/rustup/environment-variables.html).
- [Bun installation: standalone executable, version/revision checks](https://bun.sh/docs/installation).

Офіційні механізми перевірено під час планування; concrete download URLs/checksums та їх доступність перевіряються перед реалізацією manifest у Task 1.
