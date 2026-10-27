# OMP усередині Capri: запропонований дизайн

Статус: дизайн погоджено й заморожено 2026-10-27 з двома уточненнями нижче.
Standalone Task 1 proof і Task 2 snapshot/local SDK import пройшли 2026-10-27.
Переключення executable та решта runtime integration ще не починалися.
Evidence: `docs/verification/vendored-omp.md`; toolchain: `runtime-toolchain.json`.
Підстава: останні повідомлення розмови «Запропонована наступна ітерація»
(`6adf8f23-b238-83eb-8d00-33b8a20540f3`) та поточний checkout
`5d1e19506913637dc1c5d179507ba718f136257c`.

## Намір і межі

Погоджені уточнення 2026-10-27: Task 1 — окремий throwaway OMP checkout/build
без інтеграції Capri, з `--version`, мінімальним RPC prompt і native tool smoke.
Task 6 містить окремий negative dependency gate: немає global OMP, старого
`~/.omp`, GitHub downloads OMP source/binary/SDK або cached vendored build.

Перший варіант — включити закріплений OMP source у звичайне дерево Git Capri,
встановлювати Python SDK із цього дерева та збирати локальний Windows runtime.
Усі керовані Capri дані виконання залишаються в її приватному data directory,
за замовчуванням `.runtime/` у checkout. Код можна змінювати й збирати незалежно
від наступних релізів OMP. Це все ще використання OMP codebase та його RPC.

Python, Bun, Rust/MSVC і сторонні пакети залишаються build dependencies.
Завантаження залежностей із реєстрів під час bootstrap дозволене; повністю
офлайн-збірка та побітово однаковий executable не є обіцянкою цієї ітерації.
Модель і Telegram також залишаються зовнішніми сервісами. Довільні файлові
операції native tools не стають обмеженими папкою репозиторію.

Сюди не входять `soul.md`/`PERSONALITY.md`, зміна характеру/промптів, memory,
нові capabilities, скорочення OMP, оновлення upstream, єдиний Capri+OMP exe,
публікація пакетів або підтримка інших ОС. Personality — окрема наступна зміна.

## Підходи

1. **Повний pinned snapshot у `vendor/omp/` — обраний напрям у розмові.**
   Один checkout містить source, SDK, workspace, lockfiles і ліцензійні файли.
   Розмір source більший, зате зникає bootstrap-залежність від OMP repository/release.
2. Git submodule потребує окремого отримання OMP source й не задовольняє цей намір.
3. Переписування agent loop або негайне вирізання workspace значно розширює
   міграцію й ускладнює збереження поточної поведінки.

Рішення нижче — запропоновані технічні деталі реалізації першого варіанту,
а не додаткові побажання, уже погоджені користувачем.

## Перевірений початковий стан

- README і `pyproject.toml` закріплюють OMP **18.12.6**, commit
  `45c35e40c46166dc726ccc52f5d27f40f2449f99`; SHA-256 source ZIP:
  `a8bbb85ede151ed58c100e84e6d239ca835937e04a51cd287049a9ff737fd4e2`.
- CLI за замовчуванням використовує `.runtime/omp.exe`; owner і Guest отримують
  явний executable. SDK у metadata надходить з GitHub archive. У поточній venv
  він установлений із локально витягнутого SDK під `.runtime/source/`;
  це ще не відтворювана інсталяція з tracked source Capri.
- Owner pointer — `.runtime/session.json`, transcript — `.runtime/agent/sessions/`;
  Guest index — `.runtime/guest/threads.json`, transcripts —
  `.runtime/guest/sessions/<chat>/<thread>/`. Ці шляхи зберігаємо.
- `omp_environment()` задає приватний agent dir, але `PI_CONFIG_DIR=.capri-omp`
  лишає OMP config-root paths під Windows user home. Native loader окремо
  має home-based cache; для нього існує абсолютний `PI_NATIVES_DIR` override.
- Upstream workspace вимагає Bun `>=1.4`; Rust toolchain —
  `nightly-2026-10-06`. На Windows `build:native` використовує локальний
  Cargo/N-API + VS Build Tools; Bazel cross build не є Windows host path.
- Upstream `bun setup` створює глобальні links. Використовуємо окремі install,
  native build і binary build команди без setup/link/publish.
- Native host build автоматично обирає CPU ISA. Для переносимого Windows x64
  artifact треба явно забезпечити baseline, а не успадкувати AVX2 build host.
- Наявні owner tools, activity, approvals, permission persistence, Guest isolation,
  steering і строгий `stop() is True` — частина поточної поведінки, яку зберігаємо.

## Дерево та відповідальності

```text
vendor/
  omp/                         # повний upstream snapshot + задокументовані patches
    UPSTREAM.md                # repository, commit, archive hash, local differences
    packages/, crates/, sdk/, scripts/, patches/, ...
    package.json, bun.lock, Cargo.lock, LICENSE, THIRD-PARTY-NOTICES.txt, ...
  omp-source-manifest.json      # sha256 початкових файлів, поза upstream tree
scripts/
  bootstrap.ps1                # локальна Python інсталяція та виклик build
  build-runtime.ps1            # Windows toolchain, build, перевірка, promotion
  verify-vendor.py             # baseline parity з явно дозволеними patches
  smoke-runtime.py             # auth-free SDK/CLI lifecycle у тимчасовому data dir
runtime-toolchain.json          # точний перевірений build toolchain
requirements-runtime.txt       # явний local SDK path + editable Capri
.runtime/                      # усе ignored
  bin/omp.exe                  # новий основний artifact
  bin/runtime-build.json       # provenance і hashes локального build
  build/, cache/, tmp/         # build artifacts, керовані кеші, temporary files
  omp-root/                   # OMP root state: logs/stats/runtime caches
  agent/, work/, guest/        # існуючі auth/config/sessions/work, без перенесення
  owner.json, session.json, bot-token, capri-isolation.yml
```

Upstream source не скорочуємо. Не переносимо `.git`, приватний runtime або
випадкові локальні файли зі старого working copy. Зберігаємо всі source assets,
lockfiles, ліцензії й notices. Ігноруємо generated binaries/caches, а не всі
`*.json`, `*.jsonl`, `*.js` чи інші формати, які можуть бути upstream fixtures/source.
Source manifest рахується по байтах архіву; `.gitattributes` має запобігти
CRLF-перетворенню vendored source на Windows.

## Встановлення та збірка

Підтримуваний шлях — bootstrap із checkout, без звернень до upstream OMP release
або GitHub source під час звичайної інсталяції. `pyproject.toml` міститиме
`omp-rpc==0.1.0`, а `requirements-runtime.txt` явно передаватиме pip локальний
`./vendor/omp/sdk/python/omp-rpc` разом із `-e .`. Це обходить проблему переносності
відносного file URL у project metadata. Окремий `pip install -e .` не є bootstrap;
README/AGENTS/CI повинні використовувати local requirements або bootstrap.
Перевіряємо provenance встановленого SDK через distribution metadata/direct_url,
не лише номер версії. Не додаємо автоматичний fallback на однойменний пакет PyPI.

Перший implementation gate — чиста Windows x64 збірка. Треба отримати один
працездатний набір exact versions: Bun `>=1.4`, Rust `nightly-2026-10-06`,
VS C++ Build Tools + Windows SDK, CMake/Ninja та інші реально потрібні інструменти.
Версії фіксуємо після probe, не вигадуємо зараз. Toolchain manifest і його перевірка
стають входом build script; успіх на підготовленій машині ще не є clean-build proof.

Build послідовно робить frozen Bun install, local native build, генерацію потрібних
assets і `bun scripts/ci-release-build-binaries.ts --targets win32-x64`. Очікуваний
upstream output — `packages/coding-agent/binaries/omp-windows-x64.exe`.
Root `bun run build` не використовуємо: він запускає весь workspace.
Lockfiles не мають змінюватися. Додаємо лише мінімальні documented patches,
якщо для Cargo locked mode чи baseline ISA потрібне доповнення upstream scripts.

Новий artifact проходить smoke перед заміною `.runtime/bin/omp.exe`. На Windows
зайнятий exe або помилка build/smoke залишає попередній artifact доступним;
build не зупиняє bot автоматично. Старий `.runtime/omp.exe` лишається локальним
rollback шляхом через явний `--omp`, без мовчазного fallback.

## Локальні дані та зміна runtime path

Новий default: `<data>/bin/omp.exe`, де data за замовчуванням `.runtime`.
`--data` визначає і default binary, і data root; явний `--omp` має пріоритет.
Відносні CLI paths прив'язуємо до launch cwd й передаємо engines абсолютні paths.
Немає пошуку `omp` у PATH, автоматичного скачування або автооновлення upstream exe.
Telegram-only Guest probe не потребує executable.

Зберігаємо agent/session/Guest paths, pairing, auth та permission config на місці.
Для решти OMP root state пропонується мінімальний fork hook `CAPRI_OMP_ROOT`:
`packages/utils/src/dirs.ts:getBaseConfigRoot()` приймає тільки абсолютний override;
без нього upstream behavior зберігається. Capri передає `<data>/omp-root` та
`PI_NATIVES_DIR=<data>/cache/natives` однаково для owner, Guest, config CLI й login.
Не підміняємо Windows HOME/USERPROFILE: tools повинні бачити реальну машину.

Керовані Bun/Cargo/build caches та subprocess temp направляємо в ignored paths.
Audit охоплює auth, model DB, logs/stats, native extraction, on-demand installs,
update checks і workspace-generated files. Знайдені додаткові постійні записи
локалізуємо підтримуваними overrides або малими окремо описаними patches.
Зовнішні інсталятори, загальний Windows temp та файли, які користувач просить
native tools змінити поза data root, не покриваються обіцянкою «все в `.runtime`».
Не копіюємо автоматично весь старий home-based cache/config: потрібні дані
спершу інвентаризуємо, чинні auth/session paths зберігаємо без міграції.

## Приймання та відкат

Готовність означає: fresh clone Capri → local Python install → локальна native
та exe збірка → auth-free RPC smoke без глобального OMP/старих caches → тести Capri.
Окремий ручний live gate перевіряє owner restart/resume, Guest threads та handoff,
`/permission`, Once/Session/Deny, `/stop`, activity і bubbles з новим binary.
Без цього записуємо лише build/automated acceptance, не live PASS.

Rollback — зупинити Capri, запустити стару ревізію/узгоджений SDK із явним
`--omp .runtime/omp.exe` та тим самим data root. Source baseline незмінний;
перед live switch створюється ignored backup state. Session writes під час live
перевірки не оголошуємо автоматично оборотними: restore backup — окремий свідомий крок.

## Джерела для implementation

- Локальні `README.md`, `pyproject.toml`, `requirements-test.txt`, `.github/workflows/test.yml`.
- Локальні `src/capri/{cli,config,engine,guest_engine,guest_threads,teardown}.py`.
- [Pinned workspace](https://github.com/can1357/oh-my-pi/blob/45c35e40c46166dc726ccc52f5d27f40f2449f99/package.json),
  [native host driver](https://github.com/can1357/oh-my-pi/blob/45c35e40c46166dc726ccc52f5d27f40f2449f99/scripts/bazel-natives.ts),
  [native build](https://github.com/can1357/oh-my-pi/blob/45c35e40c46166dc726ccc52f5d27f40f2449f99/packages/natives/scripts/build-bindings.ts).
- [Binary build](https://github.com/can1357/oh-my-pi/blob/45c35e40c46166dc726ccc52f5d27f40f2449f99/scripts/ci-release-build-binaries.ts),
  [compile helper](https://github.com/can1357/oh-my-pi/blob/45c35e40c46166dc726ccc52f5d27f40f2449f99/packages/coding-agent/scripts/compile-binary.ts).
- [Directory resolver](https://github.com/can1357/oh-my-pi/blob/45c35e40c46166dc726ccc52f5d27f40f2449f99/packages/utils/src/dirs.ts),
  [native loader](https://github.com/can1357/oh-my-pi/blob/45c35e40c46166dc726ccc52f5d27f40f2449f99/packages/natives/native/loader-state.js),
  [Rust pin](https://github.com/can1357/oh-my-pi/blob/45c35e40c46166dc726ccc52f5d27f40f2449f99/rust-toolchain.toml).
