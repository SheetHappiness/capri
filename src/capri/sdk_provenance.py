"""Check the installed SDK's local origin before loading the application."""
import importlib.metadata as metadata
import json
from pathlib import Path


class SdkProvenanceError(RuntimeError):
    pass


def verify_sdk_provenance() -> None:
    diagnostic = ('Capri requires the SDK from this checkout. From the checkout root run:\n'
                  '.venv/Scripts/python -m pip install -r requirements-runtime.txt')
    try:
        distribution = metadata.distribution('omp-rpc')
        origin_text = distribution.read_text('direct_url.json')
        if distribution.version != '0.1.0' or origin_text is None:
            raise ValueError
        origin = json.loads(origin_text)
        if (not isinstance(origin, dict) or not isinstance(origin.get('dir_info'), dict)
                or not isinstance(origin.get('url'), str)):
            raise ValueError
        actual = Path.from_uri(origin['url'])
        expected = Path(__file__).resolve().parents[2] / 'vendor/omp/sdk/python/omp-rpc'
        if not expected.is_dir() or not actual.is_dir() or not actual.samefile(expected):
            raise ValueError
    except (metadata.PackageNotFoundError, OSError, ValueError, TypeError):
        raise SdkProvenanceError(diagnostic) from None
