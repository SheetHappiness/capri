import { afterAll, expect, test } from "bun:test";
import { $ } from "bun";
import * as fs from "node:fs/promises";
import * as path from "node:path";

interface NapiCall {
	args: string[];
	rustflags: string;
}

const sourceRoot = path.resolve(import.meta.dir, "../../..");
const scratchBase = path.resolve(sourceRoot, "../../.runtime/task4-bun-tests");
await fs.mkdir(scratchBase, { recursive: true });
const scratch = await fs.mkdtemp(path.join(scratchBase, "run-"));
afterAll(() => fs.rm(scratch, { recursive: true, force: true }));

async function write(root: string, name: string, value: string) {
	await Bun.write(path.join(root, name), value);
}

// Only the fresh child's FFI export is spied on. The test runner's host and
// registry stay untouched, and the fake reports AVX2 regardless of the CPU.
const preload = path.join(scratch, "force-avx2.ts");
await Bun.write(preload, `import { spyOn } from "bun:test";
import * as ffi from "bun:ffi";
spyOn(ffi, "dlopen").mockImplementation(() => ({
  symbols: {IsProcessorFeaturePresent: () => 1}, close() {}}));`);

const windowsTest = test.skipIf(process.platform !== "win32" || process.arch !== "x64");

async function child(args: string[], cwd: string, variant: string): Promise<string> {
	const result = await $`${process.execPath} --preload ${preload} ${args}`.cwd(cwd).env({
		...process.env, PI_NATIVE_VARIANT: variant, OMP_NATIVE_CARGO_PROFILE: "ci",
		RUSTFLAGS: "", CARGO_ENCODED_RUSTFLAGS: "", OMP_NATIVE_FEATURES: "",
		BUN_RUNTIME_TRANSPILER_CACHE_PATH: "0",
	}).quiet().nothrow();
	expect(result.exitCode, result.text() + result.stderr.toString()).toBe(0);
	return result.text();
}

windowsTest("baseline override wins over an AVX2-capable host", async () => {
	const probe = path.join(scratch, "probe.ts");
	await Bun.write(probe, `import { detectHostAvx2Support } from ${JSON.stringify(path.join(sourceRoot, "scripts/host-detect.ts"))};
console.log(JSON.stringify(detectHostAvx2Support()));`);
	expect(JSON.parse(await child([probe], scratch, ""))).toBe(true);
	expect(JSON.parse(await child([probe], scratch, "baseline"))).toBe(false);
});

async function buildFixture(): Promise<{ root: string; call: NapiCall }> {
	const root = await fs.mkdtemp(path.join(scratch, "native-"));
	for (const name of ["scripts/host-detect.ts", "scripts/stamp-native-version.ts",
		"packages/natives/scripts/build-bindings.ts", "packages/natives/scripts/gen-enums.ts",
		"packages/natives/native/version-sentinel.js", "packages/natives/native/index.js"]) {
		await Bun.write(path.join(root, name), Bun.file(path.join(sourceRoot, name)));
	}
	await write(root, "package.json", '{"type":"module"}');
	await write(root, "packages/natives/package.json", '{"name":"@oh-my-pi/pi-natives","version":"18.12.6"}');
	await write(root, "node_modules/@napi-rs/cli/package.json", '{"name":"@napi-rs/cli","bin":{"napi":"capture.mjs"}}');
	// Double only the N-API/Cargo boundary. The real driver stamps, normalizes,
	// installs and generates bindings from these synthetic compiler outputs.
	await write(root, "node_modules/@napi-rs/cli/capture.mjs", `
import * as path from "node:path";
const args = process.argv.slice(2);
await Bun.write("napi-call.json", JSON.stringify({args, rustflags: process.env.RUSTFLAGS}));
const out = args[args.indexOf("-o") + 1];
const stamp = Buffer.alloc(64); stamp.write("PI_NATIVES_VERSION_STAMP:");
await Bun.write(path.join(out, "pi_natives.win32-x64-msvc.node"), stamp);
await Bun.write(path.join(out, "index.d.ts"), "export declare function capriFixture(): void;\\n");
`);
	await child(["packages/natives/scripts/build-bindings.ts"], root, "baseline");
	const call: NapiCall = await Bun.file(path.join(root, "napi-call.json")).json();
	return { root, call };
}

windowsTest("baseline build installs the canonical filename and x86-64-v2 flags", async () => {
	const { root, call } = await buildFixture();
	expect(await Bun.file(path.join(root, "packages/natives/native/pi_natives.win32-x64-baseline.node")).exists()).toBe(true);
	expect(await Bun.file(path.join(root, "packages/natives/native/pi_natives.win32-x64-modern.node")).exists()).toBe(false);
	expect(call.rustflags).toBe("-C target-feature=+crt-static -C target-cpu=x86-64-v2");
});

windowsTest("N-API receives the actual Cargo -- --locked argv", async () => {
	const { call } = await buildFixture();
	expect(call.args.slice(-2)).toEqual(["--", "--locked"]);
	expect(call.args[call.args.indexOf("--profile") + 1]).toBe("ci");
	expect(call.args).toContain("--manifest-path");
});
