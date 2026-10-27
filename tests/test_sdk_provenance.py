import importlib.metadata as metadata
import json
from pathlib import Path
import subprocess
import sys

import pytest

from capri import sdk_provenance as provenance


@pytest.fixture
def sdk(tmp_path, monkeypatch):
    checkout = tmp_path / 'Capri копія з пробілами'
    source = checkout / 'src/capri/sdk_provenance.py'
    source.parent.mkdir(parents=True)
    source.touch()
    expected = checkout / 'vendor/omp/sdk/python/omp-rpc'
    expected.mkdir(parents=True)
    dist = tmp_path / 'omp_rpc-0.1.0.dist-info'
    dist.mkdir()
    (dist / 'METADATA').write_text('Metadata-Version: 2.1\nName: omp-rpc\nVersion: 0.1.0\n')
    (dist / 'direct_url.json').write_text(json.dumps({'url': expected.as_uri(), 'dir_info': {}}))
    distribution = metadata.PathDistribution(dist)
    monkeypatch.setattr(provenance, '__file__', str(source))
    monkeypatch.setattr(provenance.metadata, 'distribution', lambda name: distribution)
    return expected, dist


def test_accepts_checkout_sdk(sdk):
    provenance.verify_sdk_provenance()


@pytest.mark.parametrize('contents', [None, '', '{', 'null', '[]', '42',
    '{}', '{"url": "file:///private-origin"}',
    '{"url": "file:///private-origin", "dir_info": null}',
    '{"url": "file:///private-origin", "dir_info": []}',
    '{"dir_info": {}}', '{"url": 42, "dir_info": {}}'])
def test_rejects_invalid_sdk_metadata(sdk, contents):
    _, dist = sdk
    origin = dist / 'direct_url.json'
    if contents is None:
        origin.unlink()  # Distribution.read_text returns None for absent files.
    else:
        origin.write_text(contents)
    with pytest.raises(provenance.SdkProvenanceError) as error:
        provenance.verify_sdk_provenance()
    assert 'requirements-runtime.txt' in str(error.value)
    assert 'private-origin' not in str(error.value)


@pytest.mark.parametrize('kind', ['other-checkout', 'missing-directory', 'file', 'https', 'vcs'])
def test_rejects_other_sdk_origins(sdk, tmp_path, kind):
    _, dist = sdk
    other = tmp_path / 'private-other-origin'
    if kind == 'other-checkout':
        other.mkdir()
    elif kind == 'file':
        other.touch()
    url = {'https': 'https://example.invalid/private-other-origin.whl',
           'vcs': 'git+https://example.invalid/private-other-origin.git'}.get(kind, other.as_uri())
    (dist / 'direct_url.json').write_text(json.dumps({'url': url, 'dir_info': {}}))
    with pytest.raises(provenance.SdkProvenanceError) as error:
        provenance.verify_sdk_provenance()
    assert 'private-other-origin' not in str(error.value)


@pytest.mark.parametrize('failure', ['missing-distribution', 'unreadable', 'wrong-version', 'missing-source'])
def test_rejects_unavailable_sdk(sdk, monkeypatch, failure):
    expected, dist = sdk
    if failure in ('missing-distribution', 'unreadable'):
        def fail(name):
            if failure == 'missing-distribution':
                raise metadata.PackageNotFoundError('omp-rpc')
            raise PermissionError('private-origin')
        monkeypatch.setattr(provenance.metadata, 'distribution', fail)
    elif failure == 'wrong-version':
        (dist / 'METADATA').write_text('Metadata-Version: 2.1\nName: omp-rpc\nVersion: 0.2.0\n')
    else:
        expected.rmdir()
    with pytest.raises(provenance.SdkProvenanceError) as error:
        provenance.verify_sdk_provenance()
    assert 'private-origin' not in str(error.value)


def test_origin_is_independent_of_working_directory(sdk, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    provenance.verify_sdk_provenance()


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows junction alias')
def test_accepts_junction_alias(sdk, tmp_path):
    expected, dist = sdk
    alias = tmp_path / 'sdk alias'
    result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(alias), str(expected)],
                            capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
    (dist / 'direct_url.json').write_text(json.dumps({'url': alias.as_uri(), 'dir_info': {}}))
    try:
        provenance.verify_sdk_provenance()
    finally:
        alias.rmdir()  # Remove only the junction, never its target.
