/** Auth-free source probe. Run from vendor/omp with an unused absolute data dir. */
import assert from "node:assert/strict";
import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

const repo = path.resolve(import.meta.dir, "..");
const vendor = path.join(repo, "vendor/omp");
const self = fileURLToPath(import.meta.url);
const cli = path.join(vendor, "packages/coding-agent/src/cli.ts");

function within(root: string, target: string): boolean {
	const relative = path.relative(root, target);
	return relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative));
}

// This branch is a fresh process: env is installed before any OMP import.
if (process.argv[2] === "--paths-child") {
	const data = process.argv[3];
	const dirs = await import("../vendor/omp/packages/utils/src/dirs.ts");
	const native = await import("../vendor/omp/packages/natives/native/loader-state.js");
	const nativeCache = native.initLoaderContext().nativesDir;
	const root = path.join(data, "omp-root");
	assert.equal(dirs.getBaseConfigRoot(), root);
	assert.equal(dirs.getAgentDir(), path.join(data, "agent"));
	assert.equal(dirs.getSessionsDir(), path.join(data, "agent/sessions"));
	assert.equal(nativeCache, path.join(data, "cache/natives"));
	assert.equal(os.tmpdir(), path.join(data, "tmp"));
	const bunCache = Bun.spawnSync([process.execPath, "pm", "cache"], { env: { ...process.env, BUN_BE_BUN: "1" } });
	assert.equal(bunCache.exitCode, 0);
	assert.equal(bunCache.stdout.toString().trim(), path.join(data, "cache/bun"));
	assert.match(dirs.getInstallId(), /^[0-9a-f-]{36}$/);
	assert.equal((await fs.readFile(path.join(root, "install-id"), "utf8")).trim(), dirs.getInstallId());
	const targets = [dirs.getLogPath(), dirs.getStatsDbPath(), dirs.getModelDbPath(), dirs.getAgentDbPath(),
		dirs.getGlobalDaemonRuntimeDir("probe"), dirs.getSessionOwnersDir(), dirs.getToolsDir(),
		dirs.getPythonEnvDir(), dirs.getTinyModelsCacheDir(), dirs.getPluginsDir(), dirs.getPuppeteerDir()];
	for (const target of targets) assert(within(data, target), "resolver escaped data");
	// Exercise actual file writes without forging SQLite databases or runtime leases.
	for (const directory of [dirs.getLogsDir(), nativeCache, os.tmpdir()]) {
		await fs.mkdir(directory, { recursive: true });
		await fs.writeFile(path.join(directory, "capri-probe-marker"), "probe\n");
	}
	console.log(JSON.stringify({ resolver: "pass", installId: "persisted", nativeCache: "write-marker-only" }));
	process.exit(0);
}

const dataArg = process.argv[2];
assert(dataArg && path.isAbsolute(dataArg), "Supply an absolute unused scratch data directory");
const data = path.resolve(dataArg);
const runtime = path.join(repo, ".runtime");
assert(within(runtime, data) && data !== runtime, "Scratch data must be below this checkout's ignored .runtime");
// Resolve existing ancestors too: a junction must not point at active/external state.
let ancestor = data;
while (!(await fs.stat(ancestor).catch(() => null))) ancestor = path.dirname(ancestor);
assert(within(await fs.realpath(runtime), await fs.realpath(ancestor)), "Scratch ancestor escapes .runtime");
assert(!within(path.join(runtime, "agent"), data), "Refusing the active agent directory");
try {
	assert.equal((await fs.readdir(data)).length, 0, "Refusing nonempty scratch data");
} catch (error) {
	if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
}

// Only metadata is recorded; auth/config/transcript contents are never read.
async function inventory(root: string): Promise<Record<string, string>> {
	const result: Record<string, string> = {};
	async function visit(directory: string): Promise<void> {
		let entries;
		try { entries = await fs.readdir(directory, { withFileTypes: true }); }
		catch (error) {
			if ((error as NodeJS.ErrnoException).code === "ENOENT") return;
			throw error;
		}
		for (const entry of entries) {
			const full = path.join(directory, entry.name);
			const stat = await fs.lstat(full);
			result[path.relative(root, full)] = `${stat.size}:${stat.mtimeMs}:${stat.mode}`;
			if (entry.isDirectory() && !entry.isSymbolicLink()) await visit(full);
		}
	}
	await visit(root);
	return result;
}

const watched = [path.join(os.homedir(), ".omp"), path.join(os.homedir(), ".capri-omp"),
	path.join(process.env.LOCALAPPDATA ?? path.join(os.homedir(), "AppData/Local"), "omp")];
const before = await Promise.all(watched.map(inventory));
const python = path.join(repo, ".venv/Scripts/python.exe");
const prepared = Bun.spawnSync([python, "-c",
	"import json,sys; from pathlib import Path; from capri.config import omp_environment,omp_isolation_args; p=Path(sys.argv[1]); print(json.dumps({'env':omp_environment(p),'args':omp_isolation_args(p)}))", data],
	{ cwd: repo, stdout: "pipe", stderr: "pipe" });
assert.equal(prepared.exitCode, 0, "Python environment preparation failed");
const setup = JSON.parse(prepared.stdout.toString());
const env = { ...process.env, ...setup.env, NO_COLOR: "1" };
for (const key of ["HOME", "USERPROFILE"]) assert.equal(env[key], process.env[key]);
const work = path.join(data, "work");
await fs.mkdir(work, { recursive: true });

async function run(args: string[], label: string, timeout = 30_000) {
	const child = Bun.spawn([process.execPath, ...args], { cwd: work, env, stdin: "ignore", stdout: "pipe", stderr: "pipe", windowsHide: true });
	let timedOut = false;
	const timer = setTimeout(() => { timedOut = true; child.kill(); }, timeout);
	const [exitCode, stdout, stderr] = await Promise.all([child.exited, new Response(child.stdout).text(), new Response(child.stderr).text()]);
	clearTimeout(timer);
	// Raw output stays private under the disposable data tree.
	await fs.writeFile(path.join(data, `${label}.log`), stdout + stderr);
	return { exitCode, timedOut, stdout, stderr };
}

const paths = await run([self, "--paths-child", data], "paths");
assert.equal(paths.exitCode, 0, "Source resolver probe failed; see private paths.log");
// Force a cacheable TS input, independently of OMP's own source cache policy.
const fixture = path.join(work, "transpiler-probe.ts");
await fs.writeFile(fixture, Array.from({ length: 600 }, (_, i) => `const v${i}: number = ${i};`).join("\n") + "\nconsole.log(v599);\n");
const transpiler = await run([fixture], "transpiler");
assert.equal(transpiler.exitCode, 0);
assert.equal(transpiler.stdout.trim(), "599");
assert((await fs.readdir(path.join(data, "cache/transpiler"))).some(name => name.endsWith(".pile")), "No private transpiler cache write observed");
const configArgs = [cli, "config", "get", "tools.approvalMode", "--json"];
const config = await run(configArgs, "config");
const worker = await run([cli, "--smoke-test"], "worker");

// Never submit a prompt or load credentials. Read one state frame, then close stdin.
async function rpcProbe() {
	const child = Bun.spawn([process.execPath, cli, "--mode", "rpc", "--provider", "openai-codex", "--model", "gpt-6-luna",
		"--session-dir", path.join(data, "agent/sessions"), "--no-extensions", "--no-skills", "--no-rules", "--no-lsp", "--no-pty", "--no-title", ...setup.args],
		{ cwd: work, env, stdin: "pipe", stdout: "pipe", stderr: "pipe", windowsHide: true });
	let timedOut = false;
	const timer = setTimeout(() => { timedOut = true; child.kill(); }, 30_000);
	const stderr = new Response(child.stderr).text();
	let buffer = "";
	let received = false;
	let sessionInsideData = false;
	let modelMatches = false;
	const output = (async () => {
		for await (const bytes of child.stdout) {
			buffer += new TextDecoder().decode(bytes, { stream: true });
			let end;
			while ((end = buffer.indexOf("\n")) >= 0) {
				const line = buffer.slice(0, end); buffer = buffer.slice(end + 1);
				let frame;
				try { frame = JSON.parse(line); } catch { continue; }
				if (frame.id === "capri-isolation" && frame.type === "response") {
					received = frame.success === true;
					const state = frame.data;
					sessionInsideData = typeof state?.sessionFile === "string" && within(path.join(data, "agent/sessions"), path.resolve(state.sessionFile));
					modelMatches = state?.model?.provider === "openai-codex" && state?.model?.id === "gpt-6-luna";
					child.stdin.end();
				}
			}
		}
	})();
	child.stdin.write(JSON.stringify({ id: "capri-isolation", type: "get_state" }) + "\n");
	const exitCode = await child.exited;
	await output;
	clearTimeout(timer);
	await fs.writeFile(path.join(data, "rpc-stderr.log"), await stderr);
	return { received, sessionInsideData, modelMatches, exitCode, timedOut, stopped: child.exitCode !== null };
}
const rpc = await rpcProbe();
const after = await Promise.all(watched.map(inventory));
const unchanged = before.map((snapshot, i) => JSON.stringify(Object.entries(snapshot).sort()) === JSON.stringify(Object.entries(after[i]).sort()));
const configPassed = config.exitCode === 0 && !config.timedOut && (() => {
	try { const result = JSON.parse(config.stdout); return result.key === "tools.approvalMode" && typeof result.value === "string"; }
	catch { return false; }
})();
const result = {
	resolver: "pass", transpilerCache: "private .pile write observed",
	config: { passed: configPassed, exitCode: config.exitCode, timedOut: config.timedOut },
	worker: { passed: worker.exitCode === 0 && !worker.timedOut, exitCode: worker.exitCode, timedOut: worker.timedOut,
		socketPathTooLong: /ENAMETOOLONG|too long/i.test(worker.stderr) },
	rpc, homeMetadataUnchanged: unchanged, observation: "known-directory metadata snapshots; no process write tracer",
	nativeExtraction: "pending compiled binary; source addon prebuilt from same pin",
	installerNetworkPaths: "static audit only", authenticatedAcceptance: "not run",
};
await fs.writeFile(path.join(data, "result.json"), JSON.stringify(result, null, 2) + "\n");
console.log(JSON.stringify(result, null, 2));
process.exitCode = configPassed && result.worker.passed && rpc.received && rpc.modelMatches && rpc.sessionInsideData
	&& rpc.stopped && rpc.exitCode === 0 && !rpc.timedOut && unchanged.every(Boolean) ? 0 : 1;
