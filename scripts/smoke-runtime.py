"""Auth-free standalone runtime acceptance. Never submits a model prompt."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

from omp_rpc import RpcClient
from capri.config import omp_environment, omp_isolation_args


# Leave room for OMP's generated Unix-domain worker socket filename (108 bytes).
MAX_TEMP_BYTES = 70


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def run_command(argv, *, cwd, env, timeout=30):
    process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding='utf-8', errors='replace',
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name == 'nt':
            killed = subprocess.run([str(Path(env['SystemRoot']) / 'System32/taskkill.exe'),
                                     '/PID', str(process.pid), '/T', '/F'],
                                    capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
            if killed.returncode != 0 and process.poll() is None:
                raise RuntimeError('CLI timeout: process-tree teardown unconfirmed')
        else:
            process.kill()
        process.communicate(timeout=10)
        raise
    return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)


def run_smoke(executable: Path, data: Path):
    executable, data = executable.resolve(), data.resolve()
    if not executable.is_file():
        raise ValueError('Smoke requires an existing candidate executable')
    if data.exists() and (not data.is_dir() or any(data.iterdir())):
        raise ValueError('Smoke scratch must be empty')
    if len(str(data / 't').encode('utf-8')) > MAX_TEMP_BYTES:
        raise ValueError('Windows worker socket path is too long; choose a shorter Data path')
    data.mkdir(parents=True, exist_ok=True)
    report = {'schema_version': 1, 'passed': False, 'executable_sha256': digest(executable),
              **{key: False for key in ('cli', 'worker', 'config', 'rpc', 'native_extraction', 'teardown')}}
    before = dict(os.environ)
    try:
        # SDK overlays its env onto os.environ. Clear the base too so ambient
        # provider credentials/config cannot be reintroduced into RPC children.
        env = {key: before[key] for key in ('SystemRoot', 'SYSTEMROOT', 'WINDIR', 'ComSpec', 'COMSPEC',
               'PATHEXT', 'HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA') if key in before}
        env.setdefault('HOME', before.get('HOME', ''))
        env.update(omp_environment(data))
        temporary = data / 't'
        temporary.mkdir()
        env.update(TEMP=str(temporary), TMP=str(temporary), NO_COLOR='1', PI_NATIVE_VARIANT='baseline')
        env['PATH'] = str(Path(before.get('SystemRoot', 'C:/Windows')) / 'System32')
        os.environ.clear()
        os.environ.update(env)
        work = data / 'work'
        sessions = data / 'agent/sessions'
        work.mkdir()
        sessions.mkdir(parents=True)
        isolation = omp_isolation_args(data)
        for name, args in [('version', ['--version']), ('help', ['--help']),
                           ('worker', ['--smoke-test']),
                           ('config', ['config', 'get', 'tools.approvalMode', '--json'])]:
            result = run_command([str(executable), *args], cwd=work, env=env, timeout=30)
            (data / f'{name}.stdout.log').write_text(result.stdout, encoding='utf-8')
            (data / f'{name}.stderr.log').write_text(result.stderr, encoding='utf-8')
            if result.returncode != 0:
                raise RuntimeError(f'Smoke {name} exited {result.returncode}; see private logs in {data}')
            if name == 'version' and '18.12.6' not in result.stdout:
                raise RuntimeError('Unexpected OMP version')
            if name in ('worker', 'config'):
                report[name] = True
        report['cli'] = True
        client = RpcClient(executable=str(executable), cwd=work, env=env, session_dir=sessions,
                           provider='openai-codex', model='gpt-6-luna', tools=(),
                           no_skills=True, no_rules=True, no_title=True, no_ui=True,
                           extra_args=['--no-extensions', '--no-lsp', '--no-pty', *isolation],
                           startup_timeout=30, request_timeout=30)
        try:
            client.start()
            state = client.get_state()
            if not state.session_file or not Path(state.session_file).resolve().is_relative_to(sessions):
                raise RuntimeError('RPC session escaped smoke scratch')
            report['rpc'] = True
        finally:
            report['teardown'] = client.stop() is True
            if not report['teardown']:
                raise RuntimeError('RPC teardown unconfirmed')
        addons = list((data / 'cache/natives').rglob('pi_natives.win32-x64-baseline.node'))
        if not addons:
            raise RuntimeError('No embedded baseline native extraction in fresh scratch')
        report['native_sha256'] = digest(addons[0])
        report['native_extraction'] = True
        if digest(executable) != report['executable_sha256']:
            raise RuntimeError('Candidate changed during smoke')
        report['passed'] = True
        return report
    except Exception as error:
        report['failure_type'] = type(error).__name__
        raise
    finally:
        os.environ.clear()
        os.environ.update(before)
        (data / 'smoke-result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--omp', required=True, type=Path)
    parser.add_argument('--data', required=True, type=Path)
    args = parser.parse_args()
    run_smoke(args.omp, args.data)
    print('Auth-free runtime smoke passed; see smoke-result.json in the supplied Data directory.')


if __name__ == '__main__':
    main()
